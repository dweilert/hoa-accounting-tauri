"""Page service for bank statement import (OFX / CSV → reconciliation auto-match).

Transactions are stored immediately as PENDING on upload and survive navigation.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import sqlite3
from dataclasses import dataclass
from decimal import Decimal

from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.services.non_dues_income_service import IncomeRow
from hoa_accounting.web.bank_statement_import import (
    ParsedTransaction,
    ParseError,
    apply_rules,
    auto_detect_csv_columns,
    csv_map_is_usable,
    detect_format,
    find_batch_matches,
    match_transactions,
    parse_csv,
    parse_ofx,
    parse_ofx_by_account,
)
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class PageResponse:
    status_code: int
    body_html: str


class BankStatementPages:
    """Handles the bank-statement import flow tied to a reconciliation."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _render(self, template: str, **ctx) -> PageResponse:
        return PageResponse(200, render_template(template, ctx))

    def _get_unmatched_items(self, bank_account_id: int) -> list[dict]:
        """Return single-entry records for this bank account that have no
        linked bank transaction yet (i.e. no prior OFX import has claimed
        them via ``matched_source_type`` / ``matched_source_id``).

        Each item exposes ``source_type``, ``source_id``, ``item_date``,
        signed ``amount`` (positive = deposit, negative = withdrawal), and
        a short ``description`` — the matcher's expected shape. Payments
        that belong to a deposit batch are excluded; they clear as a unit
        via ``_get_unmatched_batches``.

        Exclusion scope is "any bank_transactions row has already linked
        this record" — regardless of reconciliation state. That makes OFX
        import independent from the monthly reconciliation workflow.
        """
        rows = self._conn.execute(
            """
            WITH ba AS (
                SELECT id AS bank_account_id, gl_account_id
                FROM bank_accounts WHERE id = ?
            ),
            matched AS (
                SELECT bt.matched_source_type AS source_type,
                       bt.matched_source_id   AS source_id
                FROM bank_transactions bt
                WHERE bt.matched_source_type IS NOT NULL
                  AND bt.matched_source_id   IS NOT NULL
            )
            SELECT 'PAYMENT' AS source_type, p.id AS source_id,
                   p.payment_date AS item_date,
                   CAST(p.amount AS REAL) AS amount,
                   COALESCE(p.notes, '') AS description
            FROM payments p, ba
            WHERE p.bank_account_id = ba.bank_account_id
              AND p.deposit_batch_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM matched m
                  WHERE m.source_type = 'PAYMENT' AND m.source_id = p.id
              )
            UNION ALL
            SELECT 'INCOME_BATCH', ib.id,
                   ib.posting_date,
                   CAST(ib.total_amount AS REAL),
                   COALESCE(ib.income_description, '')
            FROM income_batches ib, ba
            WHERE ib.bank_account_id = ba.bank_account_id
              AND NOT EXISTS (
                  SELECT 1 FROM matched m
                  WHERE m.source_type = 'INCOME_BATCH' AND m.source_id = ib.id
              )
            UNION ALL
            SELECT 'BILL_PAYMENT', bp.id,
                   bp.payment_date,
                   -CAST(bp.amount AS REAL),
                   COALESCE(bp.notes, '')
            FROM bill_payments bp, ba
            WHERE bp.bank_account_id = ba.bank_account_id
              AND NOT EXISTS (
                  SELECT 1 FROM matched m
                  WHERE m.source_type = 'BILL_PAYMENT' AND m.source_id = bp.id
              )
            UNION ALL
            SELECT 'RESERVE_TRANSFER', rt.id,
                   rt.transfer_date,
                   CASE WHEN rt.to_account_id = ba.gl_account_id
                        THEN  CAST(rt.amount AS REAL)
                        ELSE -CAST(rt.amount AS REAL) END,
                   COALESCE(rt.notes, '')
            FROM reserve_transfers rt, ba
            WHERE (rt.from_account_id = ba.gl_account_id
                   OR rt.to_account_id = ba.gl_account_id)
              AND NOT EXISTS (
                  SELECT 1 FROM matched m
                  WHERE m.source_type = 'RESERVE_TRANSFER' AND m.source_id = rt.id
              )
            ORDER BY item_date ASC
            """,
            (bank_account_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _get_unmatched_batches(self, bank_account_id: int) -> list[dict]:
        """Return deposit batches for this bank account that no prior OFX
        import has already matched. A batch is considered matched only when
        its deposit_batch_id appears in ``bank_transactions.matched_source_id``
        with ``matched_source_type = 'DEPOSIT_BATCH'``.
        """
        rows = self._conn.execute(
            """
            SELECT db.id AS batch_id,
                   db.deposit_date AS batch_date,
                   CAST(db.total_amount AS REAL) AS total_amount,
                   COALESCE(db.notes, '') AS notes,
                   (SELECT COUNT(*) FROM payments p
                    WHERE p.deposit_batch_id = db.id) AS member_count
            FROM deposit_batches db
            WHERE db.bank_account_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM bank_transactions bt
                  WHERE bt.matched_source_type = 'DEPOSIT_BATCH'
                    AND bt.matched_source_id   = db.id
              )
            ORDER BY db.deposit_date ASC
            """,
            (bank_account_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _batch_member_payment_ids(self, batch_id: int) -> list[int]:
        rows = self._conn.execute(
            "SELECT id FROM payments WHERE deposit_batch_id = ? ORDER BY id",
            (batch_id,),
        ).fetchall()
        return [int(r["id"]) for r in rows]

    def _load_rules(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT r.id, r.rule_name, r.description_contains,
                   r.match_type, r.match_memo, r.match_amount, r.bank_account_id,
                   r.action_type, r.category_id, r.vendor_id, r.lot_id,
                   r.default_memo, r.active_flag,
                   r.confidence_mode, r.auto_post_after_n, r.confirmed_matches,
                   c.name AS category_name,
                   v.vendor_name AS vendor_name
            FROM bank_transaction_rules r
            LEFT JOIN categories c ON c.id = r.category_id
            LEFT JOIN vendors    v ON v.id = r.vendor_id
            WHERE r.active_flag = 1
            ORDER BY r.id
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def _next_receipt_number(self, payment_date: str) -> str:
        prefix = "RCT-" + payment_date.replace("-", "") + "-"
        row = self._conn.execute(
            "SELECT receipt_number FROM payments WHERE receipt_number LIKE ? ORDER BY receipt_number DESC LIMIT 1",
            (prefix + "%",),
        ).fetchone()
        seq = int(row["receipt_number"].rsplit("-", 1)[1]) + 1 if row else 1
        return f"{prefix}{seq:04d}"

    def _open_assessments_for_lot(self, lot_id: int) -> list[int]:
        """Return IDs of open/partial assessments for a lot, oldest due_date first."""
        rows = self._conn.execute(
            """
            SELECT a.id
            FROM assessments a
            LEFT JOIN payment_applications pa ON pa.assessment_id = a.id
            WHERE a.lot_id = ? AND a.status IN ('OPEN', 'PARTIAL')
            GROUP BY a.id, a.amount, a.due_date
            HAVING a.amount - COALESCE(SUM(pa.applied_amount), 0) > 0
            ORDER BY a.due_date ASC
            """,
            (lot_id,),
        ).fetchall()
        return [int(r["id"]) for r in rows]

    def _apply_rule(
        self,
        txn_row: dict,
        rule: dict,
        bank_account_id: int,
    ) -> tuple[str, int] | None:
        """Post a single-entry record representing this bank transaction.

        Returns ``(source_type, source_id)`` identifying the row that was
        created (for linking back from the bank transaction and the
        reconciliation), or ``None`` if the rule can't be applied — missing
        vendor, missing category, missing lot owner, or the transaction sign
        doesn't fit the action type. Callers decide what to do on None
        (typically leave the bank transaction unmatched and surface a hint).
        """
        factory = ServiceFactory(self._conn)
        action = str(rule.get("action_type") or "")
        amount = Decimal(str(txn_row["amount"]))
        txn_date = txn_row["transaction_date"]
        description = (rule.get("default_memo") or txn_row.get("description") or "").strip()
        category_id = rule.get("category_id")
        category_id_int = int(category_id) if category_id else None

        # Incoming owner payment ─ applies to open assessments oldest first.
        if action == "dues_payment":
            if amount <= 0:
                return None
            lot_id = rule.get("lot_id")
            if not lot_id:
                return None
            owner_row = self._conn.execute(
                """SELECT owner_id FROM lot_ownership
                   WHERE lot_id = ? AND end_date IS NULL
                   ORDER BY start_date DESC LIMIT 1""",
                (int(lot_id),),
            ).fetchone()
            if not owner_row:
                return None
            receipt_number = self._next_receipt_number(txn_date)
            result = factory.payment_service().post_payment(
                entry_date=txn_date,
                owner_id=int(owner_row["owner_id"]),
                amount=str(amount),
                description=description,
                bank_account_id=bank_account_id,
                payment_method="ACH",
                receipt_number=receipt_number,
                apply_to_assessment_ids=self._open_assessments_for_lot(int(lot_id)),
            )
            if category_id_int is not None:
                self._conn.execute(
                    "UPDATE payments SET category_id = ? WHERE id = ?",
                    (category_id_int, result.payment_id),
                )
            return ("PAYMENT", result.payment_id)

        # Incoming non-owner income (fees, interest, misc).
        if action in ("fee_income", "direct_income"):
            if amount <= 0 or category_id_int is None:
                return None
            result = factory.non_dues_income_service().post_batch(
                posting_date=txn_date,
                bank_account_id=bank_account_id,
                income_description=description or "Bank import",
                rows=[IncomeRow(amount=str(amount), other_source="BANK")],
                category_id=category_id_int,
            )
            return ("INCOME_BATCH", result.income_batch_id)

        # Outgoing expense — needs both a vendor and a category.
        if action in ("recurring_bill", "direct_expense", "bank_charge"):
            if amount >= 0:
                return None
            vendor_id = rule.get("vendor_id")
            if not vendor_id or category_id_int is None:
                return None
            amt = abs(amount)
            invoice_number = f"BR-{txn_date.replace('-', '')}-{int(txn_row['id']):06d}"
            bill = factory.vendor_bill_service().post_vendor_bill(
                entry_date=txn_date,
                vendor_id=int(vendor_id),
                amount=str(amt),
                description=description,
                invoice_number=invoice_number,
                invoice_date=txn_date,
                category_id=category_id_int,
            )
            payment = factory.vendor_payment_service().post_vendor_payment(
                entry_date=txn_date,
                vendor_bill_id=bill.vendor_bill_id,
                amount=str(amt),
                description=description,
                bank_account_id=bank_account_id,
            )
            if category_id_int is not None:
                self._conn.execute(
                    "UPDATE bill_payments SET category_id = ? WHERE id = ?",
                    (category_id_int, payment.bill_payment_id),
                )
            return ("BILL_PAYMENT", payment.bill_payment_id)

        # homeowner_batch and vendor_bill_match don't post records — they
        # match transactions to existing single-entry rows via other paths.
        return None

    def _period_for_date(self, date_str: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM accounting_periods WHERE ? BETWEEN start_date AND end_date LIMIT 1",
            (date_str,),
        ).fetchone()
        return int(row["id"]) if row else None

    def _compute_matches(
        self,
        transactions: list[ParsedTransaction],
        items: list[dict],
        batches: list[dict],
        rules: list[dict],
        bank_account_id: int | None = None,
    ) -> tuple[
        dict[int, dict],
        dict[int, tuple[str, int]],
        dict[int, int],
    ]:
        """Return (rule_matches, source_matches, batch_matches).

        Priority is RULE → SOURCE (1:1 against a single-entry record) →
        BATCH (deposit_batch by total amount). Each transaction ends up in
        at most one bucket.
        """
        rule_m = apply_rules(transactions, rules, bank_account_id=bank_account_id)
        rule_skips = set(rule_m.keys())
        source_m = match_transactions(transactions, items, skip_indices=rule_skips)
        source_and_rule = rule_skips | set(source_m.keys())
        batch_m = find_batch_matches(
            transactions, batches, skip_indices=source_and_rule,
        )
        return rule_m, source_m, batch_m

    @staticmethod
    def _dedup_key(txn, bank_account_id: int) -> str:
        """Per-account unique key. Prefers the canonical record's hash so
        identity is bank-agnostic and FITID-independent; falls back to a
        content-based key for legacy ``ParsedTransaction`` callers during
        cutover."""
        from hoa_accounting.web.bank_ingest import CanonicalBankTxn
        if isinstance(txn, CanonicalBankTxn):
            return txn.dedup_key(bank_account_id)
        # Legacy ParsedTransaction — compute the same hash from its fields
        # so mixed callers produce identical keys.
        raw = "|".join([
            str(bank_account_id),
            txn.transaction_date.isoformat(),
            str(txn.amount),
            txn.description or "",
            txn.memo or "",
            (txn.transaction_type or "").upper(),
            "",  # check_number not available on ParsedTransaction
        ])
        return "h:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _insert_bank_txn(
        self,
        *,
        bank_account_id: int,
        batch_id: int,
        txn: ParsedTransaction,
        idx: int,
        rule_m: dict[int, dict],
        source_m: dict[int, tuple[str, int]],
        batch_m: dict[int, int],
    ) -> bool:
        """Insert one bank_transactions row; return True if a new row was written.

        Uses INSERT OR IGNORE against the (bank_account_id, dedup_key) unique
        index so re-importing a file, or importing overlapping OFX ranges,
        silently dedupes.

        Priority for the proposed match recorded on the row:
        RULE > SOURCE > BATCH > UNMATCHED. A match is a *proposal* only — the
        row still lands with validation_status='UNVALIDATED' so the user sees
        it in the Pending Validation queue and decides whether to post.
        """
        rule_id: int | None = None
        matched_source_type: str | None = None
        matched_source_id: int | None = None

        if idx in rule_m:
            match_type = "RULE"
            rule_id = int(rule_m[idx]["id"])
        elif idx in source_m:
            match_type = "SOURCE"
            matched_source_type, matched_source_id = source_m[idx]
        elif idx in batch_m:
            match_type = "BATCH"
            matched_source_type = "DEPOSIT_BATCH"
            matched_source_id = int(batch_m[idx])
        else:
            match_type = "UNMATCHED"

        dedup_key = self._dedup_key(txn, bank_account_id)
        recon_status = "UNMATCHED" if match_type == "UNMATCHED" else "MATCHED"

        cur = self._conn.execute(
            """
            INSERT OR IGNORE INTO bank_transactions
                (bank_account_id, import_batch_id, transaction_date,
                 description, memo, amount, external_reference,
                 transaction_type, reconciliation_status,
                 match_type, rule_id,
                 matched_source_type, matched_source_id,
                 dedup_key, validation_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bank_account_id, batch_id,
                txn.transaction_date.isoformat(),
                txn.description, txn.memo, str(txn.amount),
                txn.fitid, txn.transaction_type,
                recon_status,
                match_type, rule_id,
                matched_source_type, matched_source_id,
                dedup_key, "UNVALIDATED",
            ),
        )
        if cur.rowcount == 1:
            return True

        # Conflict on (bank_account_id, dedup_key) — row already exists. For
        # unvalidated rows, refresh the proposed match so re-running rules
        # produces current suggestions. Validated rows are left alone; their
        # ledger links are authoritative and shouldn't be clobbered.
        self._conn.execute(
            """
            UPDATE bank_transactions
               SET match_type = ?, rule_id = ?,
                   matched_source_type = ?, matched_source_id = ?,
                   reconciliation_status = ?
             WHERE bank_account_id = ? AND dedup_key = ?
               AND validation_status = 'UNVALIDATED'
            """,
            (
                match_type, rule_id,
                matched_source_type, matched_source_id,
                recon_status,
                bank_account_id, dedup_key,
            ),
        )
        return False

    def _store_pending_batch(
        self,
        *,
        reconciliation_id: int | None,
        bank_account_id: int,
        filename: str,
        file_format: str,
        file_bytes: bytes,
        csv_col_map: dict,
        transactions: list[ParsedTransaction],
        items: list[dict],
        batches: list[dict],
        rules: list[dict],
    ) -> int:
        """Insert PENDING batch + all transactions. Returns batch_id."""
        rule_m, source_m, batch_m = self._compute_matches(
            transactions, items, batches, rules, bank_account_id=bank_account_id
        )
        match_count = len(rule_m) + len(source_m) + len(batch_m)

        cur = self._conn.execute(
            """
            INSERT INTO bank_import_batches
                (bank_account_id, reconciliation_id, source_filename,
                 file_format, transaction_count, matched_count,
                 status, file_content, csv_col_map)
            VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """,
            (
                bank_account_id, reconciliation_id, filename,
                file_format, len(transactions), match_count,
                file_bytes, json.dumps(csv_col_map),
            ),
        )
        batch_id = int(cur.lastrowid)  # type: ignore[arg-type]

        # Dedup is enforced by the (bank_account_id, dedup_key) unique index;
        # INSERT OR IGNORE returns rowcount=0 for a duplicate. We keep track
        # of how many rows actually landed — and how many of those were
        # proposed matches — so the batch audit row reflects reality.
        inserted = 0
        inserted_matches = 0
        auto_posted = 0
        for i, txn in enumerate(transactions):
            was_new = self._insert_bank_txn(
                bank_account_id=bank_account_id,
                batch_id=batch_id,
                txn=txn,
                idx=i,
                rule_m=rule_m,
                source_m=source_m,
                batch_m=batch_m,
            )
            if was_new:
                inserted += 1
                if i in rule_m or i in source_m or i in batch_m:
                    inserted_matches += 1

            # Auto-post rules skip the review queue: post the ledger record
            # and flip validation_status to VALIDATED right at ingest. Only
            # applies to fresh rows — re-imports of an already-posted line
            # are left alone.
            if was_new and i in rule_m:
                rule = rule_m[i]
                if str(rule.get("confidence_mode") or "review_first") == "auto_post":
                    if self._auto_post_rule_match(txn, rule, bank_account_id):
                        auto_posted += 1

        self._conn.execute(
            "UPDATE bank_import_batches SET transaction_count = ?, matched_count = ? WHERE id = ?",
            (inserted, inserted_matches, batch_id),
        )
        self._conn.commit()
        return batch_id

    def _auto_post_rule_match(
        self,
        txn: ParsedTransaction,
        rule: dict,
        bank_account_id: int,
    ) -> bool:
        """Post a ledger record for an auto-post rule match and mark the
        bank transaction VALIDATED. Returns True on success, False if the
        rule couldn't be applied (missing vendor/category/lot, wrong sign,
        etc.) — in which case the row stays UNVALIDATED for the user to
        handle in the Pending Validation queue.
        """
        row = self._conn.execute(
            "SELECT id, transaction_date, description, amount FROM bank_transactions "
            "WHERE bank_account_id = ? AND dedup_key = ?",
            (bank_account_id, self._dedup_key(txn, bank_account_id)),
        ).fetchone()
        if row is None:
            return False
        result = self._apply_rule(dict(row), dict(rule), bank_account_id=bank_account_id)
        if result is None:
            return False
        source_type, source_id = result
        self._conn.execute(
            """
            UPDATE bank_transactions
               SET matched_source_type = ?, matched_source_id = ?,
                   validation_status = 'VALIDATED'
             WHERE id = ?
            """,
            (source_type, int(source_id), int(row["id"])),
        )
        self._conn.execute(
            """
            INSERT OR IGNORE INTO bank_transaction_links
                (bank_transaction_id, ledger_source_type, ledger_source_id,
                 link_source, rule_id)
            VALUES (?, ?, ?, 'RULE', ?)
            """,
            (int(row["id"]), source_type, int(source_id), int(rule["id"])),
        )
        self._conn.execute(
            "UPDATE bank_transaction_rules SET confirmed_matches = confirmed_matches + 1 WHERE id = ?",
            (int(rule["id"]),),
        )
        return True

    # ── Standalone import (no reconciliation) ────────────────────────────────

    def _get_bank_account(self, bank_account_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT id, account_name, account_last4, institution_name, gl_account_id FROM bank_accounts WHERE id = ?",
            (bank_account_id,),
        ).fetchone()

    def _get_all_bank_accounts(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, account_name, account_last4, institution_name FROM bank_accounts ORDER BY account_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def _get_all_batches(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT b.id, b.bank_account_id, b.source_filename, b.file_format,
                   b.transaction_count, b.matched_count, b.status, b.imported_at,
                   ba.account_name, ba.account_last4
            FROM bank_import_batches b
            JOIN bank_accounts ba ON ba.id = b.bank_account_id
            WHERE b.reconciliation_id IS NULL
            ORDER BY b.imported_at DESC
            LIMIT 50
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def render_agnostic_upload_form(
        self, org: dict, theme: str,
        error: str | None = None,
        success: str | None = None,
    ) -> PageResponse:
        """Combined import history + upload form — no account pre-selection needed."""
        bank_accounts = self._get_all_bank_accounts()
        batches = self._get_all_batches()
        return self._render(
            "bank_import.html",
            org=org, theme=theme,
            page_key="bank-import",
            bank_accounts=bank_accounts,
            batches=batches,
            error=error,
            success=success,
        )

    def handle_agnostic_upload(
        self,
        file_bytes: bytes,
        filename: str,
        csv_bank_account_id: int | None,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        """Account-agnostic upload.

        Routes through the ingest adapter registry: the dispatcher picks
        the right parser (OFX/CSV/…), the adapter emits canonical records,
        and this method is format-agnostic past that point. OFX retains
        its ACCTID-split special case because one file can span multiple
        accounts; other adapters target a single selected account.
        """
        from hoa_accounting.web.bank_ingest import (
            canonical_from_parsed, dispatch,
        )

        def _err(msg: str) -> tuple[None, PageResponse]:
            return None, self.render_agnostic_upload_form(org, theme, error=msg)

        try:
            choice = dispatch(file_bytes)
        except ParseError as e:
            return _err(str(e))

        rules = self._load_rules()
        adapter_name = choice.adapter.name

        # OFX keeps its multi-account routing: one file can hold sections
        # for every bank account at the institution, each tagged with an
        # ACCTID we match to ``bank_accounts.account_last4``.
        if adapter_name == "ofx":
            try:
                account_sections = parse_ofx_by_account(file_bytes)
            except Exception as exc:
                return _err(f"Could not read OFX file: {exc}")

            created: list[tuple[int, int, str]] = []
            skipped: list[str] = []

            for acctid, parsed_txns in account_sections:
                last4 = acctid[-4:] if acctid else ""
                row = self._conn.execute(
                    "SELECT id, account_name FROM bank_accounts WHERE account_last4 = ?", (last4,)
                ).fetchone() if last4 else None
                if row is None:
                    skipped.append(acctid or "(no ACCTID)")
                    continue

                matched_bank_id = int(row["id"])
                canonical = [canonical_from_parsed(p, p.transaction_type)
                             for p in parsed_txns]
                batch_id = self._store_pending_batch(
                    reconciliation_id=None,
                    bank_account_id=matched_bank_id,
                    filename=filename, file_format="OFX",
                    file_bytes=file_bytes, csv_col_map={},
                    transactions=canonical,
                    items=self._get_unmatched_items(matched_bank_id),
                    batches=self._get_unmatched_batches(matched_bank_id),
                    rules=rules,
                )
                created.append((batch_id, matched_bank_id, row["account_name"]))

            if not created:
                return _err(
                    "No recognized bank accounts found. Unrecognized IDs: "
                    + ", ".join(skipped)
                )
            acct_names = ", ".join(name for _, _, name in created)
            total_txns = sum(
                self._conn.execute(
                    "SELECT transaction_count FROM bank_import_batches WHERE id = ?", (b_id,)
                ).fetchone()["transaction_count"]
                for b_id, _, _ in created
            )
            msg = f"Imported {total_txns} transactions into {acct_names}."
            if skipped:
                msg += f" Skipped unrecognized account IDs: {', '.join(skipped)}."
            return f"/bank-import/upload?ok=1&msg={msg}", None

        # CSV-style adapter — one account per upload. If the dispatcher
        # says ``needs_mapping`` we consult the saved column-map store
        # first; a previously-mapped shape (same headers as a prior
        # upload) parses silently. A truly new shape is stashed and the
        # user is redirected into the mapping wizard.
        from hoa_accounting.web.bank_ingest import (
            fingerprint_csv_headers, lookup_csv_mapping, read_csv_headers,
            stash_upload,
        )

        if not csv_bank_account_id:
            return _err("Please select which bank account this file is for.")
        ba = self._get_bank_account(csv_bank_account_id)
        if not ba:
            return _err("Selected bank account not found.")

        mapping: dict | None = None
        if choice.needs_mapping:
            fp = fingerprint_csv_headers(file_bytes)
            mapping = lookup_csv_mapping(self._conn, csv_bank_account_id, fp)
            if mapping is None:
                # First time seeing this CSV shape for this account. Stash
                # the bytes and hand off to the mapping wizard; once the
                # user saves a mapping, the save-mapping endpoint replays
                # the upload with the new mapping in hand.
                token = stash_upload(
                    self._conn, csv_bank_account_id,
                    filename or "upload.csv", file_bytes,
                )
                headers = ",".join(read_csv_headers(file_bytes)[:6])
                preview = (f"This CSV from {ba['account_name']} uses a column layout "
                           f"we haven't seen before ({headers}…). Map its columns "
                           f"to the canonical fields to continue.")
                from urllib.parse import quote
                return (
                    f"/admin/import?prefill_type=bank_statement_csv"
                    f"&stash={token}&bank_account_id={csv_bank_account_id}"
                    f"&note={quote(preview)}",
                    None,
                )

        try:
            canonical = choice.adapter.parse(file_bytes, mapping=mapping)
        except Exception as exc:
            return _err(f"Could not read file: {exc}")

        batch_id = self._store_pending_batch(
            reconciliation_id=None,
            bank_account_id=csv_bank_account_id,
            filename=filename, file_format=adapter_name.upper(),
            file_bytes=file_bytes, csv_col_map={},
            transactions=canonical,
            items=self._get_unmatched_items(csv_bank_account_id),
            batches=self._get_unmatched_batches(csv_bank_account_id),
            rules=rules,
        )
        msg = f"Imported {len(canonical)} transactions into {ba['account_name']}."
        return f"/bank-import/upload?ok=1&msg={msg}", None

    def render_standalone_upload_form(
        self,
        bank_account_id: int,
        org: dict,
        theme: str,
        error: str | None = None,
    ) -> PageResponse:
        ba = self._get_bank_account(bank_account_id)
        if not ba:
            return PageResponse(404, render_template("error.html", {
                "org": org, "theme": theme,
                "heading": "Not Found",
                "message": "Bank account not found.",
                "page_key": "bank-accounts",
            }))
        return self._render(
            "bank_statement_upload.html",
            org=org, theme=theme,
            page_key="bank-import",
            bank_account=dict(ba),
            recon=None,
            pending=None,
            error=error,
            upload_action=f"/bank-accounts/{bank_account_id}/import-statement/upload",
            cancel_url=f"/bank-accounts/{bank_account_id}/import-statement",
        )

    def handle_standalone_upload(
        self,
        bank_account_id: int,
        file_bytes: bytes,
        filename: str,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        ba = self._get_bank_account(bank_account_id)
        if not ba:
            return None, PageResponse(404, render_template("error.html", {
                "org": org, "theme": theme,
                "heading": "Not Found",
                "message": "Bank account not found.",
                "page_key": "bank-accounts",
            }))

        try:
            file_format = detect_format(file_bytes)
        except ParseError as e:
            return None, self.render_standalone_upload_form(bank_account_id, org, theme, error=str(e))

        rules = self._load_rules()

        if file_format == "OFX":
            # ── Multi-account OFX path ──────────────────────────────────────
            try:
                account_sections = parse_ofx_by_account(file_bytes)
            except Exception as exc:
                return None, self.render_standalone_upload_form(
                    bank_account_id, org, theme,
                    error=f"Could not read OFX file: {exc}",
                )

            created_batches: list[tuple[int, int, str]] = []  # (batch_id, ba_id, account_name)
            skipped_acctids: list[str] = []

            for acctid, transactions in account_sections:
                last4 = acctid[-4:] if acctid else ""
                if last4:
                    matched_row = self._conn.execute(
                        "SELECT id, account_name FROM bank_accounts WHERE account_last4 = ?",
                        (last4,),
                    ).fetchone()
                else:
                    matched_row = None

                if matched_row is None:
                    # Fall back to the account the user navigated from when there
                    # is no ACCTID in the file (single-account OFX with no header).
                    if not acctid and len(account_sections) == 1:
                        matched_id = bank_account_id
                        matched_name = ba["account_name"]
                    else:
                        skipped_acctids.append(acctid or "(no ACCTID)")
                        continue
                else:
                    matched_id = int(matched_row["id"])
                    matched_name = matched_row["account_name"]

                batch_id = self._store_pending_batch(
                    reconciliation_id=None,
                    bank_account_id=matched_id,
                    filename=filename,
                    file_format=file_format,
                    file_bytes=file_bytes,
                    csv_col_map={},
                    transactions=transactions,
                    items=self._get_unmatched_items(matched_id),
                    batches=self._get_unmatched_batches(matched_id),
                    rules=rules,
                )
                created_batches.append((batch_id, matched_id, matched_name))

            # Zero batches created → all sections were unrecognized
            if not created_batches:
                msg = (
                    "No recognized bank accounts found in this OFX file. "
                    "Unrecognized account IDs: "
                    + ", ".join(skipped_acctids)
                )
                return None, self.render_standalone_upload_form(
                    bank_account_id, org, theme, error=msg
                )

            # Single batch → go straight to its preview
            if len(created_batches) == 1:
                b_id, b_ba_id, _name = created_batches[0]
                return f"/bank-accounts/{b_ba_id}/import-statement/{b_id}", None

            # Multiple batches → send to the All Imports list for the original account
            return f"/bank-accounts/{bank_account_id}/import-statement", None

        else:
            # ── CSV path (single-account, unchanged) ───────────────────────
            try:
                transactions, _headers, csv_col_map = parse_csv(file_bytes)
            except Exception as exc:
                return None, self.render_standalone_upload_form(
                    bank_account_id, org, theme,
                    error=f"Could not read CSV file: {exc}",
                )
            if not csv_map_is_usable(csv_col_map):
                transactions = []

            batch_id = self._store_pending_batch(
                reconciliation_id=None,
                bank_account_id=bank_account_id,
                filename=filename,
                file_format=file_format,
                file_bytes=file_bytes,
                csv_col_map=csv_col_map,
                transactions=transactions,
                items=items, batches=batches,
                rules=rules,
            )
            return f"/bank-accounts/{bank_account_id}/import-statement/{batch_id}", None

    def render_standalone_batch_preview(
        self,
        bank_account_id: int,
        batch_id: int,
        org: dict,
        theme: str,
        error: str | None = None,
    ) -> PageResponse:
        ba = self._get_bank_account(bank_account_id)
        if not ba:
            return PageResponse(404, render_template("error.html", {
                "org": org, "theme": theme,
                "heading": "Not Found",
                "message": "Bank account not found.",
                "page_key": "bank-accounts",
            }))

        batch = self._conn.execute(
            """
            SELECT id, source_filename, file_format, transaction_count, matched_count,
                   csv_col_map, status, imported_at
            FROM bank_import_batches
            WHERE id = ? AND bank_account_id = ? AND reconciliation_id IS NULL
            """,
            (batch_id, bank_account_id),
        ).fetchone()
        if not batch:
            return PageResponse(404, render_template("error.html", {
                "org": org, "theme": theme,
                "heading": "Not Found",
                "message": "Import batch not found.",
                "page_key": "bank-accounts",
            }))

        txn_rows = self._conn.execute(
            """
            SELECT bt.id, bt.transaction_date, bt.description, bt.memo, bt.amount,
                   bt.transaction_type, bt.matched_line_id, bt.match_type,
                   bt.batch_match_ids, bt.rule_id,
                   r.rule_name, r.action_type, r.default_memo,
                   COALESCE(rc.name, ra.account_name) AS rule_category_name,
                   je.entry_date     AS gl_entry_date,
                   je.memo           AS gl_memo,
                   jel.description   AS gl_line_desc,
                   CAST(jel.debit_amount  AS REAL) AS gl_debit,
                   CAST(jel.credit_amount AS REAL) AS gl_credit
            FROM bank_transactions bt
            LEFT JOIN bank_transaction_rules r  ON r.id  = bt.rule_id
            LEFT JOIN categories rc             ON rc.id = r.category_id
            LEFT JOIN accounts ra               ON ra.id = r.gl_account_id
            LEFT JOIN journal_entry_lines jel   ON jel.id = bt.matched_line_id
            LEFT JOIN journal_entries je        ON je.id  = jel.journal_entry_id
            WHERE bt.import_batch_id = ?
            ORDER BY bt.transaction_date ASC, bt.id ASC
            """,
            (batch_id,),
        ).fetchall()

        annotated = []
        for row in txn_rows:
            d = dict(row)
            if d["match_type"] == "RULE":
                d["has_period"] = self._period_for_date(d["transaction_date"]) is not None
            d["rule_action_type"] = d.get("action_type") or ""
            annotated.append(d)

        col_map = json.loads(batch["csv_col_map"] or "{}")

        headers: list[str] = []
        if batch["file_format"] == "CSV":
            fb = self._conn.execute(
                "SELECT file_content FROM bank_import_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if fb and fb["file_content"]:
                try:
                    _, headers, _ = parse_csv(fb["file_content"])
                except Exception:
                    pass

        counts = {
            "rule":      sum(1 for a in annotated if a["match_type"] == "RULE"),
            "gl":        sum(1 for a in annotated if a["match_type"] == "GL"),
            "batch":     sum(1 for a in annotated if a["match_type"] == "BATCH"),
            "unmatched": sum(1 for a in annotated if a["match_type"] == "UNMATCHED"),
        }

        base_url = f"/bank-accounts/{bank_account_id}/import-statement/{batch_id}"

        return self._render(
            "bank_statement_standalone_preview.html",
            org=org, theme=theme,
            page_key="bank-import",
            bank_account=dict(ba),
            batch=dict(batch),
            annotated=annotated,
            counts=counts,
            col_map=col_map,
            headers=headers,
            map_is_usable=(
                csv_map_is_usable(col_map) if col_map else batch["file_format"] == "OFX"
            ),
            error=error,
            base_url=base_url,
            bank_account_id=bank_account_id,
        )

    def handle_standalone_remap(
        self,
        bank_account_id: int,
        batch_id: int,
        form_data: dict,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        ba = self._get_bank_account(bank_account_id)
        if not ba:
            return f"/bank-accounts/{bank_account_id}/import-statement", None

        fb = self._conn.execute(
            "SELECT file_content FROM bank_import_batches WHERE id = ? AND bank_account_id = ? AND reconciliation_id IS NULL AND status = 'PENDING'",
            (batch_id, bank_account_id),
        ).fetchone()
        if not fb or not fb["file_content"]:
            resp = self.render_standalone_batch_preview(
                bank_account_id, batch_id, org, theme,
                error="File data not found — please re-upload.",
            )
            return None, resp

        col_map: dict[str, str] = {}
        for key in ("date", "amount", "debit", "credit", "description"):
            val = form_data.get(f"col_{key}", "").strip()
            if val:
                col_map[key] = val
        if "amount" in col_map:
            col_map.pop("debit", None)
            col_map.pop("credit", None)

        try:
            transactions, _headers, resolved = parse_csv(fb["file_content"], col_map)
        except Exception as exc:
            resp = self.render_standalone_batch_preview(
                bank_account_id, batch_id, org, theme,
                error=f"Could not re-parse CSV: {exc}",
            )
            return None, resp

        rules = self._load_rules()
        items = self._get_unmatched_items(bank_account_id)
        batches = self._get_unmatched_batches(bank_account_id)
        rule_m, source_m, batch_m = self._compute_matches(
            transactions, items, batches, rules, bank_account_id=bank_account_id
        )
        match_count = len(rule_m) + len(source_m) + len(batch_m)

        # Only drop rows that were first-seen by this batch AND are still
        # unvalidated — upsert below will refresh matches for any row that
        # was introduced by an earlier batch and reappears here.
        self._conn.execute(
            """
            DELETE FROM bank_transactions
             WHERE import_batch_id = ?
               AND validation_status = 'UNVALIDATED'
            """,
            (batch_id,),
        )

        for i, txn in enumerate(transactions):
            self._insert_bank_txn(
                bank_account_id=bank_account_id,
                batch_id=batch_id,
                txn=txn,
                idx=i,
                rule_m=rule_m,
                source_m=source_m,
                batch_m=batch_m,
            )

        self._conn.execute(
            """
            UPDATE bank_import_batches
            SET transaction_count = ?, matched_count = ?, csv_col_map = ?
            WHERE id = ?
            """,
            (len(transactions), match_count, json.dumps(resolved), batch_id),
        )
        self._conn.commit()

        return f"/bank-accounts/{bank_account_id}/import-statement/{batch_id}", None

    # handle_standalone_apply / handle_standalone_reapply removed: the
    # Pending Validation queue is the canonical review path and auto_post
    # rules post at ingest time. Routes were deleted in step 7; these
    # methods are deleted here to finish that cleanup.

    def handle_standalone_delete(
        self,
        bank_account_id: int,
        batch_id: int,
    ) -> str:
        self._conn.execute(
            "DELETE FROM bank_import_batches WHERE id = ? AND bank_account_id = ? AND reconciliation_id IS NULL",
            (batch_id, bank_account_id),
        )
        self._conn.commit()
        return f"/bank-accounts/{bank_account_id}/import-statement"

    # DEBIT-type OFX transaction types (money out) → search vendor bills
    _DEBIT_TYPES = {"DEBIT", "CHECK", "PAYMENT", "ATM", "POS", "SRVCHG", "FEE", "DIRECTDEBIT", "REPEATPMT"}

    def handle_standalone_find(
        self,
        bank_account_id: int,
        batch_id: int,
        txn_type: str,
        amount_str: str,
        date_str: str,
        ofx_desc: str = "",
        ofx_memo: str = "",
    ) -> dict:
        """Return JSON-serialisable dict with matching bills or homeowner payments."""
        try:
            amount = float(Decimal(amount_str.lstrip("$").replace(",", "")))
        except Exception:
            return {"error": "Invalid amount"}

        is_debit = txn_type.upper() in self._DEBIT_TYPES

        if is_debit:
            rows = self._conn.execute(
                """
                SELECT vb.id, vb.invoice_number, vb.invoice_date, vb.due_date,
                       CAST(vb.amount AS REAL) AS amount, vb.status, vb.description,
                       v.vendor_name
                FROM vendor_bills vb
                JOIN vendors v ON v.id = vb.vendor_id
                WHERE vb.status IN ('OPEN', 'PARTIAL')
                  AND ABS(CAST(vb.amount AS REAL) - ?) < 0.015
                ORDER BY ABS(julianday(vb.due_date) - julianday(?))
                """,
                (amount, date_str),
            ).fetchall()
            return {"type": "bills", "bills": [dict(r) for r in rows]}

        else:
            rows = self._conn.execute(
                """
                SELECT p.id, p.owner_id, p.receipt_number, p.payment_date,
                       CAST(p.amount AS REAL) AS amount, p.payment_method,
                       o.display_name AS owner_name,
                       lo.lot_id, l.lot_number
                FROM payments p
                JOIN owners o ON o.id = p.owner_id
                LEFT JOIN (
                    SELECT owner_id, MIN(lot_id) AS lot_id
                    FROM lot_ownership WHERE end_date IS NULL GROUP BY owner_id
                ) lo ON lo.owner_id = o.id
                LEFT JOIN lots l ON l.id = lo.lot_id
                WHERE p.payment_date BETWEEN date(?, '-3 days') AND date(?, '+3 days')
                ORDER BY p.payment_date, p.amount DESC
                """,
                (date_str, date_str),
            ).fetchall()
            candidates = [dict(r) for r in rows]
            target = amount

            # Build map of lot_id → all owner display_names (for multi-owner lots)
            lot_ids = list({c["lot_id"] for c in candidates if c["lot_id"]})
            lot_owner_names: dict[int, list[str]] = {}
            if lot_ids:
                placeholders = ",".join("?" * len(lot_ids))
                for r in self._conn.execute(
                    f"SELECT lo.lot_id, o.display_name FROM lot_ownership lo "
                    f"JOIN owners o ON o.id = lo.owner_id "
                    f"WHERE lo.lot_id IN ({placeholders}) AND lo.end_date IS NULL",
                    lot_ids,
                ):
                    lot_owner_names.setdefault(r["lot_id"], []).append(r["display_name"])

            # Collect rule-matched transactions: text words + amount for each.
            rule_records: list[dict] = []
            for r in self._conn.execute(
                "SELECT description, memo, CAST(amount AS REAL) AS amount "
                "FROM bank_transactions "
                "WHERE import_batch_id = ? AND match_type = 'RULE'",
                (batch_id,),
            ):
                words: set[str] = set()
                for fld in (r["description"], r["memo"]):
                    if fld:
                        words.update(w for w in re.findall(r"\b\w+\b", fld.lower()) if len(w) > 2)
                rule_records.append({"words": words, "amount": r["amount"]})

            # Text from the current OFX transaction itself.
            curr_texts = [t.lower() for t in (ofx_desc, ofx_memo) if t]

            def _name_tokens(names: list[str]) -> list[str]:
                tokens = []
                for n in names:
                    tokens.extend(p for p in n.lower().split() if len(p) > 2)
                return tokens

            def _token_hits_words(tok: str, words: set[str]) -> bool:
                """True if tok exactly matches a word, or either is a prefix of the other."""
                return any(
                    tok == w or tok.startswith(w) or w.startswith(tok)
                    for w in words
                )

            def _any_token_matches_texts(tokens: list[str], texts: list[str]) -> bool:
                return bool(tokens and any(
                    re.search(r"\b" + re.escape(tok) + r"\b", txt)
                    for tok in tokens for txt in texts
                ))

            for c in candidates:
                # Include all co-owners of the same lot for name matching
                all_names = lot_owner_names.get(c["lot_id"], [c["owner_name"] or ""])
                tokens = _name_tokens(all_names)
                # A rule-matched transaction handles this payment when:
                #   1. a co-owner name token appears in the rule transaction text, AND
                #   2. the rule transaction amount matches the payment amount.
                c["rule_handled"] = bool(tokens and any(
                    abs(rec["amount"] - c["amount"]) < 0.015
                    and any(_token_hits_words(tok, rec["words"]) for tok in tokens)
                    for rec in rule_records
                ))
                c["in_description"] = _any_token_matches_texts(tokens, curr_texts)
                c["date_match"] = (c["payment_date"] == date_str)
                c["exact_match"] = abs(c["amount"] - target) < 0.015

            # Sort: same-date first, then by date, rule_handled last within each group
            candidates.sort(key=lambda c: (
                0 if c["date_match"] else 1,
                c["payment_date"],
                1 if c["rule_handled"] else 0,
            ))

            # Subset-sum on non-handled candidates first; fall back to all
            primary = [c for c in candidates if not c["rule_handled"]]
            pool = primary if primary else candidates

            combos: list[dict] = []
            checked = 0
            outer_done = False
            for r in range(2, len(pool) + 1):
                if outer_done:
                    break
                for combo in itertools.combinations(pool, r):
                    checked += 1
                    if abs(sum(p["amount"] for p in combo) - target) < 0.015:
                        combos.append({
                            "ids": [p["id"] for p in combo],
                            "owner_names": [p["owner_name"] or "—" for p in combo],
                            "total": round(sum(p["amount"] for p in combo), 2),
                        })
                        if len(combos) >= 5:
                            outer_done = True
                            break
                    if checked >= 10000:
                        outer_done = True
                        break

            return {
                "type": "payments",
                "target": target,
                "date": date_str,
                "candidates": candidates,
                "combinations": combos,
            }


    def handle_apply_find_match(
        self,
        bank_account_id: int,
        batch_id: int,
        txn_id: int,
        payment_ids: list[int],
    ) -> dict:
        """Store the homeowner payment IDs that explain a batch deposit."""
        txn = self._conn.execute(
            "SELECT id FROM bank_transactions WHERE id = ? AND import_batch_id = ?",
            (txn_id, batch_id),
        ).fetchone()
        if not txn:
            return {"ok": False, "error": "Transaction not found in this batch"}
        if not payment_ids:
            return {"ok": False, "error": "No payment IDs provided"}
        self._conn.execute(
            "UPDATE bank_transactions SET matched_payment_ids = ? WHERE id = ?",
            (json.dumps(payment_ids), txn_id),
        )
        self._conn.commit()
        return {"ok": True}

    def handle_apply_bill_match(
        self,
        bank_account_id: int,
        batch_id: int,
        txn_id: int,
        bill_ids: list[int],
    ) -> dict:
        """Link a debit transaction to the vendor bill(s) it pays and mark them PAID."""
        txn = self._conn.execute(
            "SELECT id FROM bank_transactions WHERE id = ? AND import_batch_id = ?",
            (txn_id, batch_id),
        ).fetchone()
        if not txn:
            return {"ok": False, "error": "Transaction not found in this batch"}
        if not bill_ids:
            return {"ok": False, "error": "No bill IDs provided"}
        self._conn.execute(
            "UPDATE bank_transactions SET matched_bill_ids = ? WHERE id = ?",
            (json.dumps(bill_ids), txn_id),
        )
        placeholders = ",".join("?" * len(bill_ids))
        self._conn.execute(
            f"UPDATE vendor_bills SET status = 'PAID' WHERE id IN ({placeholders})",
            bill_ids,
        )
        self._conn.commit()
        return {"ok": True}


    def render_standalone_batch_list(
        self,
        bank_account_id: int,
        org: dict,
        theme: str,
    ) -> PageResponse:
        ba = self._get_bank_account(bank_account_id)
        if not ba:
            return PageResponse(404, render_template("error.html", {
                "org": org, "theme": theme,
                "heading": "Not Found",
                "message": "Bank account not found.",
                "page_key": "bank-accounts",
            }))

        batches = self._conn.execute(
            """
            SELECT id, source_filename, file_format, transaction_count, matched_count,
                   status, imported_at
            FROM bank_import_batches
            WHERE bank_account_id = ? AND reconciliation_id IS NULL
            ORDER BY id DESC
            """,
            (bank_account_id,),
        ).fetchall()

        applied_id = None
        try:
            from flask import request as _req
            applied_id = _req.args.get("applied", type=int)
        except Exception:
            pass

        return self._render(
            "bank_statement_import_list.html",
            org=org, theme=theme,
            page_key="bank-import",
            bank_account=dict(ba),
            batches=[dict(b) for b in batches],
            bank_account_id=bank_account_id,
            applied_id=applied_id,
        )
