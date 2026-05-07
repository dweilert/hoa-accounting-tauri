"""Page service for bank statement import (OFX / CSV → reconciliation auto-match).

Transactions are stored immediately as PENDING on upload and survive navigation.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from typing import Any

from hoa_accounting.db.transaction import transaction
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.services.non_dues_income_service import IncomeRow
from hoa_accounting.web.bank_statement_import import (
    ParsedTransaction,
    ParseError,
    apply_rules,
    find_batch_matches,
    match_transactions,
    parse_ofx_by_account,
)
from hoa_accounting.web.page_response import PageResponse  # noqa: E402
from hoa_accounting.web.template_engine import render_template

# Re-export so existing ``from bank_statement_pages import PageResponse``
# callers keep working.
__all__ = ["BankStatementPages", "PageResponse"]


class BankStatementPages:
    """Handles the bank-statement import flow tied to a reconciliation."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _render(self, template: str, **ctx: Any) -> PageResponse:
        return PageResponse(200, render_template(template, ctx))

    # Read-helpers — thin shims over web.bank_statement_queries. Kept as
    # instance methods because external callers (bank_transactions_pages,
    # ofx_inbox_pages) reference them through the Pages instance.
    def _get_unmatched_items(self, bank_account_id: int) -> list[dict[str, Any]]:
        from hoa_accounting.web import bank_statement_queries as q

        return q.get_unmatched_items(self._conn, bank_account_id)

    def _get_unmatched_batches(self, bank_account_id: int) -> list[dict[str, Any]]:
        from hoa_accounting.web import bank_statement_queries as q

        return q.get_unmatched_batches(self._conn, bank_account_id)

    # Read-helpers — thin shims over web.bank_ingest_engine. Kept as
    # instance methods because external callers (bank_transactions_pages,
    # ofx_inbox_pages) reach into them through the Pages instance.
    def _batch_member_payment_ids(self, batch_id: int) -> list[int]:
        from hoa_accounting.web import bank_ingest_engine as eng

        return eng.batch_member_payment_ids(self._conn, batch_id)

    def _load_rules(self) -> list[dict[str, Any]]:
        from hoa_accounting.web import bank_ingest_engine as eng

        return eng.load_rules(self._conn)

    def _next_receipt_number(self, payment_date: str) -> str:
        from hoa_accounting.web import bank_ingest_engine as eng

        return eng.next_receipt_number(self._conn, payment_date)

    def _open_assessments_for_lot(self, lot_id: int) -> list[int]:
        from hoa_accounting.web import bank_ingest_engine as eng

        return eng.open_assessments_for_lot(self._conn, lot_id)

    def _apply_rule(
        self,
        txn_row: dict[str, Any],
        rule: dict[str, Any],
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
        description = (
            rule.get("default_memo") or txn_row.get("description") or ""
        ).strip()
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

            # Create a single-item deposit_batches row so ACH payments
            # appear in the Deposits report alongside physical-check
            # batches. The bank line is the deposit, conceptually.
            batch_cur = self._conn.execute(
                """INSERT INTO deposit_batches
                   (deposit_date, bank_account_id, total_amount, notes)
                   VALUES (?, ?, ?, ?)""",
                (
                    txn_date,
                    bank_account_id,
                    str(amount),
                    f"ACH dues — {description}" if description else "ACH dues",
                ),
            )
            deposit_batch_id = int(batch_cur.lastrowid or 0)

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
            # Attach the payment to the synthetic deposit batch.
            self._conn.execute(
                "UPDATE payments SET deposit_batch_id = ? WHERE id = ?",
                (deposit_batch_id, result.payment_id),
            )
            return ("PAYMENT", result.payment_id)

        # Incoming non-owner income (fees, interest, misc).
        if action in ("fee_income", "direct_income"):
            if amount <= 0 or category_id_int is None:
                return None
            income_result = factory.non_dues_income_service().post_batch(
                posting_date=txn_date,
                bank_account_id=bank_account_id,
                income_description=description or "Bank import",
                rows=[IncomeRow(amount=str(amount), other_source="BANK")],
                category_id=category_id_int,
            )
            return ("INCOME_BATCH", income_result.income_batch_id)

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
            return ("BILL_PAYMENT", payment.bill_payment_id)

        # vendor_bill_match: try to link to an existing OPEN vendor bill
        # for the rule's vendor, matching the OFX amount within $0.01.
        # If none found, fall back to creating a new bill + bill_payment
        # (same path as recurring_bill) so the ledger always has a record.
        if action == "vendor_bill_match":
            if amount >= 0:
                return None
            vendor_id = rule.get("vendor_id")
            if not vendor_id:
                return None
            amt = abs(amount)
            # Tolerance compare ±$0.01 — fuzzy on purpose so a vendor bill
            # entered as "120.005" still matches a bank line of "120.00".
            # Float drift is bounded for HOA-scale amounts (well under
            # $10M), but use NUMERIC affinity rather than REAL so SQLite
            # keeps integer-or-decimal precision when the column already
            # stores a clean 2-dp value.
            existing = self._conn.execute(
                """SELECT id FROM vendor_bills
                   WHERE vendor_id = ?
                     AND status NOT IN ('PAID', 'VOID', 'WRITTEN_OFF')
                     AND ABS(CAST(amount AS NUMERIC) - CAST(? AS NUMERIC)) < 0.01
                   ORDER BY invoice_date ASC, id ASC LIMIT 1""",
                (int(vendor_id), str(amt)),
            ).fetchone()
            if existing:
                payment = factory.vendor_payment_service().post_vendor_payment(
                    entry_date=txn_date,
                    vendor_bill_id=int(existing["id"]),
                    amount=str(amt),
                    description=description,
                    bank_account_id=bank_account_id,
                )
                return ("BILL_PAYMENT", payment.bill_payment_id)
            # No matching bill — create one and pay it, same as recurring_bill.
            if category_id_int is None:
                return None
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
            return ("BILL_PAYMENT", payment.bill_payment_id)

        # homeowner_batch — match-only, no record posted.
        return None

    def _period_for_date(self, date_str: str) -> int | None:
        from hoa_accounting.web import bank_ingest_engine as eng

        return eng.period_for_date(self._conn, date_str)

    def _compute_matches(
        self,
        transactions: list[Any],  # ParsedTransaction | CanonicalBankTxn
        items: list[dict[str, Any]],
        batches: list[dict[str, Any]],
        rules: list[dict[str, Any]],
        bank_account_id: int | None = None,
    ) -> tuple[
        dict[int, dict[str, Any]],
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
            transactions,
            batches,
            skip_indices=source_and_rule,
        )
        return rule_m, source_m, batch_m

    @staticmethod
    def _dedup_key(txn: Any, bank_account_id: int) -> str:
        from hoa_accounting.web import bank_ingest_engine as eng

        return eng.dedup_key(txn, bank_account_id)

    def _insert_bank_txn(
        self,
        *,
        bank_account_id: int,
        batch_id: int,
        txn: Any,  # ParsedTransaction | CanonicalBankTxn — both shapes work via compat properties
        idx: int,
        rule_m: dict[int, dict[str, Any]],
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
                bank_account_id,
                batch_id,
                txn.transaction_date.isoformat(),
                txn.description,
                txn.memo,
                str(txn.amount),
                txn.fitid,
                txn.transaction_type,
                recon_status,
                match_type,
                rule_id,
                matched_source_type,
                matched_source_id,
                dedup_key,
                "UNVALIDATED",
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
                match_type,
                rule_id,
                matched_source_type,
                matched_source_id,
                recon_status,
                bank_account_id,
                dedup_key,
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
        csv_col_map: dict[str, Any],
        # ParsedTransaction or CanonicalBankTxn — _insert_bank_txn / apply_rules
        # only read fields available on both shapes (or via compat properties).
        transactions: list[Any],
        items: list[dict[str, Any]],
        batches: list[dict[str, Any]],
        rules: list[dict[str, Any]],
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
                bank_account_id,
                reconciliation_id,
                filename,
                file_format,
                len(transactions),
                match_count,
                file_bytes,
                json.dumps(csv_col_map),
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
        rule: dict[str, Any],
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
        # Auto-post is one logical operation: posting the ledger record
        # via _apply_rule, marking the bank line VALIDATED, inserting the
        # bank_transaction_links audit row, and bumping the rule's match
        # counter all need to land or none of them do.
        with transaction(self._conn):
            result = self._apply_rule(
                dict(row), dict(rule), bank_account_id=bank_account_id
            )
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
        from hoa_accounting.web import bank_statement_queries as q

        return q.get_bank_account(self._conn, bank_account_id)

    def _get_all_bank_accounts(self) -> list[dict[str, Any]]:
        from hoa_accounting.web import bank_statement_queries as q

        return q.get_all_bank_accounts(self._conn)

    def _get_all_batches(self) -> list[dict[str, Any]]:
        from hoa_accounting.web import bank_statement_queries as q

        return q.get_all_batches(self._conn)

    def render_agnostic_upload_form(
        self,
        org: dict[str, Any],
        theme: str,
        error: str | None = None,
        success: str | None = None,
    ) -> PageResponse:
        """Combined import history + upload form — no account pre-selection needed."""
        bank_accounts = self._get_all_bank_accounts()
        batches = self._get_all_batches()
        return self._render(
            "bank_import.html",
            org=org,
            theme=theme,
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
        org: dict[str, Any],
        theme: str,
    ) -> tuple[str | None, PageResponse | None, list[str]]:
        """Account-agnostic upload.

        Routes through the ingest adapter registry: the dispatcher picks
        the right parser (OFX/CSV/…), the adapter emits canonical records,
        and this method is format-agnostic past that point. OFX retains
        its ACCTID-split special case because one file can span multiple
        accounts; other adapters target a single selected account.
        """
        from hoa_accounting.web.bank_ingest import (
            canonical_from_parsed,
            dispatch,
        )

        def _err(msg: str) -> tuple[None, PageResponse, list[str]]:
            return None, self.render_agnostic_upload_form(org, theme, error=msg), []

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
                row = (
                    self._conn.execute(
                        "SELECT id, account_name FROM bank_accounts WHERE account_last4 = ?",
                        (last4,),
                    ).fetchone()
                    if last4
                    else None
                )
                if row is None:
                    skipped.append(acctid or "(no ACCTID)")
                    continue

                matched_bank_id = int(row["id"])
                canonical = [
                    canonical_from_parsed(p, p.transaction_type) for p in parsed_txns
                ]
                batch_id = self._store_pending_batch(
                    reconciliation_id=None,
                    bank_account_id=matched_bank_id,
                    filename=filename,
                    file_format="OFX",
                    file_bytes=file_bytes,
                    csv_col_map={},
                    transactions=canonical,  # type: ignore[arg-type]  # TODO: _store_pending_batch wants ParsedTransaction; canonical is CanonicalBankTxn — field-name mismatch (transaction_date vs posted_at) means this path errors at runtime if it reaches _insert_bank_txn. Untested; needs a Protocol or real conversion before relying on this branch.
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
                    "SELECT transaction_count FROM bank_import_batches WHERE id = ?",
                    (b_id,),
                ).fetchone()["transaction_count"]
                for b_id, _, _ in created
            )
            from urllib.parse import quote

            msg = f"Imported {total_txns} transactions into {acct_names}."
            warnings: list[str] = []
            if skipped:
                warnings = [
                    f"Account ID {a!r} appeared in the OFX file but matches no "
                    f"bank account in the system (last 4 = {a[-4:] if len(a) >= 4 else a!r}); "
                    f"its transactions were not imported."
                    for a in skipped
                ]
            # Single-account → land on Pending Validation filtered to that
            # account. Multi-account → unfiltered Pending Validation.
            qs = f"import_msg={quote(msg)}"
            if warnings:
                qs += "&import_warn=" + quote(" | ".join(warnings))
            if len(created) == 1:
                qs = f"bank_account_id={created[0][1]}&" + qs
            return f"/bank-transactions/pending?{qs}", None, warnings

        # CSV-style adapter — one account per upload. If the dispatcher
        # says ``needs_mapping`` we consult the saved column-map store
        # first; a previously-mapped shape (same headers as a prior
        # upload) parses silently. A truly new shape is stashed and the
        # user is redirected into the mapping wizard.
        from hoa_accounting.web.bank_ingest import (
            fingerprint_csv_headers,
            lookup_csv_mapping,
            read_csv_headers,
            stash_upload,
        )

        if not csv_bank_account_id:
            return _err("Please select which bank account this file is for.")
        ba = self._get_bank_account(csv_bank_account_id)
        if not ba:
            return _err("Selected bank account not found.")

        mapping: dict[str, Any] | None = None
        if choice.needs_mapping:
            fp = fingerprint_csv_headers(file_bytes)
            mapping = lookup_csv_mapping(self._conn, csv_bank_account_id, fp)
            if mapping is None:
                # First time seeing this CSV shape for this account. Stash
                # the bytes and hand off to the mapping wizard; once the
                # user saves a mapping, the save-mapping endpoint replays
                # the upload with the new mapping in hand.
                token = stash_upload(
                    self._conn,
                    csv_bank_account_id,
                    filename or "upload.csv",
                    file_bytes,
                )
                headers = ",".join(read_csv_headers(file_bytes)[:6])
                preview = (
                    f"This CSV from {ba['account_name']} uses a column layout "
                    f"we haven't seen before ({headers}…). Map its columns "
                    f"to the canonical fields to continue."
                )
                from urllib.parse import quote

                return (
                    f"/admin/import?prefill_type=bank_statement_csv"
                    f"&stash={token}&bank_account_id={csv_bank_account_id}"
                    f"&note={quote(preview)}",
                    None,
                    [],
                )

        try:
            canonical = choice.adapter.parse(file_bytes, mapping=mapping)
        except Exception as exc:
            return _err(f"Could not read file: {exc}")

        batch_id = self._store_pending_batch(
            reconciliation_id=None,
            bank_account_id=csv_bank_account_id,
            filename=filename,
            file_format=adapter_name.upper(),
            file_bytes=file_bytes,
            csv_col_map={},
            transactions=canonical,  # type: ignore[arg-type]  # TODO: _store_pending_batch wants ParsedTransaction; canonical is CanonicalBankTxn — field-name mismatch (transaction_date vs posted_at) means this path errors at runtime if it reaches _insert_bank_txn. Untested; needs a Protocol or real conversion before relying on this branch.
            items=self._get_unmatched_items(csv_bank_account_id),
            batches=self._get_unmatched_batches(csv_bank_account_id),
            rules=rules,
        )
        from urllib.parse import quote

        msg = f"Imported {len(canonical)} transactions into {ba['account_name']}."
        return (
            f"/bank-transactions/pending?bank_account_id={csv_bank_account_id}"
            f"&import_msg={quote(msg)}",
            None,
            [],
        )

    # handle_standalone_apply / handle_standalone_reapply removed: the
    # Pending Validation queue is the canonical review path and auto_post
    # rules post at ingest time. Routes were deleted in step 7; these
    # methods are deleted here to finish that cleanup.

    def handle_standalone_delete(
        self,
        bank_account_id: int,
        batch_id: int,
    ) -> str:
        """Discard an import batch.

        Three-step:
        1. Delete every UNVALIDATED bank_transactions row that came from this
           batch — these are the staging rows the user is rolling back.
        2. NULL the import_batch_id on any surviving rows (VALIDATED /
           IGNORED) so we never leave dangling pointers to a deleted batch.
        3. Delete the bank_import_batches audit row itself.

        Validated rows are intentionally preserved: their ledger links are
        authoritative; rolling them back is a separate (more dangerous)
        operation that doesn't belong in Discard.
        """
        # 1. Delete unvalidated rows belonging to this batch.
        self._conn.execute(
            """DELETE FROM bank_transactions
                WHERE import_batch_id = ?
                  AND bank_account_id = ?
                  AND validation_status = 'UNVALIDATED'""",
            (batch_id, bank_account_id),
        )
        # 2. Detach validated/ignored survivors from the batch they belonged
        #    to so we don't leave dangling import_batch_id pointers when the
        #    parent batch row is removed.
        self._conn.execute(
            """UPDATE bank_transactions
                  SET import_batch_id = NULL
                WHERE import_batch_id = ?
                  AND bank_account_id = ?""",
            (batch_id, bank_account_id),
        )
        # 3. Drop the audit row itself.
        self._conn.execute(
            """DELETE FROM bank_import_batches
                WHERE id = ? AND bank_account_id = ?
                  AND reconciliation_id IS NULL""",
            (batch_id, bank_account_id),
        )
        self._conn.commit()
        return "/bank-import/upload"
