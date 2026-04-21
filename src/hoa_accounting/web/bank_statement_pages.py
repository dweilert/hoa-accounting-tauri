"""Page service for bank statement import (OFX / CSV → reconciliation auto-match).

Transactions are stored immediately as PENDING on upload and survive navigation.
"""

from __future__ import annotations

import itertools
import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal

from hoa_accounting.web.transaction_rule_pages import action_pattern
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

    def _get_recon(self, reconciliation_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT br.id, br.status, br.statement_ending_date,
                   br.bank_account_id,
                   ba.account_name, ba.institution_name, ba.account_last4,
                   ba.gl_account_id
            FROM bank_reconciliations br
            JOIN bank_accounts ba ON ba.id = br.bank_account_id
            WHERE br.id = ?
            """,
            (reconciliation_id,),
        ).fetchone()

    def _get_uncleared_lines(self, reconciliation_id: int) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT jel.id AS line_id,
                   je.entry_date,
                   je.memo,
                   CAST(jel.debit_amount  AS REAL) AS debit_amount,
                   CAST(jel.credit_amount AS REAL) AS credit_amount,
                   jel.description AS line_description
            FROM journal_entry_lines jel
            JOIN journal_entries je ON je.id = jel.journal_entry_id
            JOIN bank_reconciliations br ON br.id = ?
            JOIN bank_accounts ba
                ON ba.id = br.bank_account_id
               AND ba.gl_account_id = jel.account_id
            WHERE je.status = 'POSTED'
              AND je.entry_date <= br.statement_ending_date
              AND jel.id NOT IN (
                    SELECT rc.journal_entry_line_id
                    FROM reconciliation_clears rc
                    JOIN bank_reconciliations br2 ON br2.id = rc.reconciliation_id
                    WHERE br2.bank_account_id = ba.id
              )
            ORDER BY je.entry_date ASC, jel.id ASC
            """,
            (reconciliation_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _get_pending_batch(self, reconciliation_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT id, source_filename, file_format, transaction_count, matched_count,
                   csv_col_map, imported_at
            FROM bank_import_batches
            WHERE reconciliation_id = ? AND status = 'PENDING'
            ORDER BY id DESC LIMIT 1
            """,
            (reconciliation_id,),
        ).fetchone()

    def _load_rules(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT r.id, r.rule_name, r.description_contains,
                   r.match_type, r.match_memo, r.match_amount, r.bank_account_id,
                   r.action_type, r.gl_account_id, r.lot_id, r.default_memo, r.active_flag,
                   a.account_number, a.account_name
            FROM bank_transaction_rules r
            LEFT JOIN accounts a ON a.id = r.gl_account_id
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

    def _record_ar_payment(
        self,
        lot_id: int,
        je_id: int,
        bank_account_id: int,
        amount: Decimal,
        txn_date: str,
        description: str,
    ) -> None:
        """Insert a payment record + apply to open assessments for the lot."""
        owner_row = self._conn.execute(
            """SELECT lo.owner_id FROM lot_ownership lo
               WHERE lo.lot_id = ? AND lo.end_date IS NULL
               ORDER BY lo.start_date DESC LIMIT 1""",
            (lot_id,),
        ).fetchone()
        if not owner_row:
            return

        owner_id = owner_row["owner_id"]
        receipt_number = self._next_receipt_number(txn_date)

        cur = self._conn.execute(
            """
            INSERT INTO payments
                (receipt_number, owner_id, payment_date, amount,
                 payment_method, bank_account_id, journal_entry_id, notes)
            VALUES (?, ?, ?, ?, 'ACH', ?, ?, ?)
            """,
            (receipt_number, owner_id, txn_date, str(amount),
             bank_account_id, je_id, description),
        )
        payment_id = int(cur.lastrowid)  # type: ignore[arg-type]

        # Apply to oldest open assessments first
        asmt_rows = self._conn.execute(
            """
            SELECT a.id, a.amount,
                   COALESCE(SUM(pa.applied_amount), 0) AS already_applied
            FROM assessments a
            LEFT JOIN payment_applications pa ON pa.assessment_id = a.id
            WHERE a.lot_id = ? AND a.status IN ('OPEN', 'PARTIAL')
            GROUP BY a.id
            HAVING a.amount - already_applied > 0
            ORDER BY a.due_date ASC
            """,
            (lot_id,),
        ).fetchall()

        remaining = amount
        for asmt in asmt_rows:
            if remaining <= 0:
                break
            outstanding = Decimal(str(asmt["amount"])) - Decimal(str(asmt["already_applied"]))
            apply_amt = min(remaining, outstanding)
            self._conn.execute(
                """INSERT OR IGNORE INTO payment_applications
                       (payment_id, assessment_id, applied_amount)
                   VALUES (?, ?, ?)""",
                (payment_id, asmt["id"], str(apply_amt)),
            )
            new_applied = Decimal(str(asmt["already_applied"])) + apply_amt
            status = "PAID" if new_applied >= Decimal(str(asmt["amount"])) else "PARTIAL"
            self._conn.execute(
                "UPDATE assessments SET status = ? WHERE id = ?",
                (status, asmt["id"]),
            )
            remaining -= apply_amt

    def _period_for_date(self, date_str: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM accounting_periods WHERE ? BETWEEN start_date AND end_date LIMIT 1",
            (date_str,),
        ).fetchone()
        return int(row["id"]) if row else None

    def _next_entry_number(self, entry_date: str) -> str:
        prefix = "JE-" + entry_date.replace("-", "")
        row = self._conn.execute(
            "SELECT entry_number FROM journal_entries WHERE entry_number LIKE ? ORDER BY entry_number DESC LIMIT 1",
            (prefix + "%",),
        ).fetchone()
        seq = int(row["entry_number"][-4:]) + 1 if row else 1
        return f"{prefix}-{seq:04d}"

    def _compute_matches(
        self,
        transactions: list[ParsedTransaction],
        gl_lines: list[dict],
        rules: list[dict],
        bank_account_id: int | None = None,
    ) -> tuple[dict[int, dict], dict[int, int], dict[int, list[int]]]:
        """Return (rule_matches, gl_matches, batch_matches). Priority: RULE > GL > BATCH."""
        rule_m = apply_rules(transactions, rules, bank_account_id=bank_account_id)
        rule_skips = set(rule_m.keys())
        gl_m = match_transactions(transactions, gl_lines, skip_indices=rule_skips)
        gl_and_rule = rule_skips | set(gl_m.keys())
        batch_m = find_batch_matches(
            transactions, gl_lines,
            already_matched=set(gl_m.values()),
            skip_indices=gl_and_rule,
        )
        return rule_m, gl_m, batch_m

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
        gl_lines: list[dict],
        rules: list[dict],
    ) -> int:
        """Insert PENDING batch + all transactions. Returns batch_id."""
        rule_m, gl_m, batch_m = self._compute_matches(
            transactions, gl_lines, rules, bank_account_id=bank_account_id
        )
        match_count = len(rule_m) + len(gl_m) + len(batch_m)

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

        # Build set of FITIDs already stored for this bank account so we skip duplicates.
        existing_fitids: set[str] = set()
        for row in self._conn.execute(
            "SELECT external_reference FROM bank_transactions WHERE bank_account_id = ? AND external_reference != ''",
            (bank_account_id,),
        ):
            existing_fitids.add(row["external_reference"])

        inserted = 0
        for i, txn in enumerate(transactions):
            # Skip OFX transactions we've already imported (identified by FITID).
            if txn.fitid and txn.fitid in existing_fitids:
                continue

            if i in rule_m:
                match_type = "RULE"
                matched_line_id = None
                rule_id = rule_m[i]["id"]
                batch_ids_str = "[]"
            elif i in gl_m:
                match_type = "GL"
                matched_line_id = gl_m[i]
                rule_id = None
                batch_ids_str = "[]"
            elif i in batch_m:
                match_type = "BATCH"
                matched_line_id = None
                rule_id = None
                batch_ids_str = json.dumps(batch_m[i])
            else:
                match_type = "UNMATCHED"
                matched_line_id = None
                rule_id = None
                batch_ids_str = "[]"

            self._conn.execute(
                """
                INSERT INTO bank_transactions
                    (bank_account_id, import_batch_id, transaction_date,
                     description, memo, amount, external_reference,
                     transaction_type, matched_line_id, reconciliation_status,
                     match_type, batch_match_ids, rule_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bank_account_id, batch_id,
                    txn.transaction_date.isoformat(),
                    txn.description, txn.memo, str(txn.amount),
                    txn.fitid, txn.transaction_type,
                    matched_line_id,
                    "UNMATCHED" if match_type == "UNMATCHED" else "MATCHED",
                    match_type, batch_ids_str, rule_id,
                ),
            )
            inserted += 1

        # Update batch counts to reflect only what was actually inserted.
        self._conn.execute(
            "UPDATE bank_import_batches SET transaction_count = ?, matched_count = ? WHERE id = ?",
            (inserted, min(match_count, inserted), batch_id),
        )
        self._conn.commit()
        return batch_id

    def _create_rule_je(
        self,
        txn_row: dict,
        rule: dict,
        bank_gl_account_id: int,
        period_id: int,
    ) -> tuple[int, int]:
        """Create a journal entry for a rule-matched transaction.

        direct_expense: DR gl_account / CR bank
        direct_income:  DR bank / CR gl_account

        Returns (je_id, bank_line_id).
        """
        entry_date = txn_row["transaction_date"]
        entry_num = self._next_entry_number(entry_date)
        memo = rule.get("default_memo") or txn_row.get("description") or ""
        gl_account_id = int(rule["gl_account_id"])
        amount = str(abs(Decimal(str(txn_row["amount"]))))

        cur = self._conn.execute(
            """
            INSERT INTO journal_entries (entry_number, entry_date, memo, status, accounting_period_id)
            VALUES (?, ?, ?, 'POSTED', ?)
            """,
            (entry_num, entry_date, memo, period_id),
        )
        je_id = int(cur.lastrowid)  # type: ignore[arg-type]

        pattern = action_pattern(rule.get("action_type", "recurring_bill"))
        if pattern == "expense":
            lines = [
                (1, gl_account_id,       amount, "0"),    # DR expense/charge acct
                (2, bank_gl_account_id,  "0",    amount), # CR bank
            ]
            bank_line_num = 2
        else:
            lines = [
                (1, bank_gl_account_id,  amount, "0"),    # DR bank
                (2, gl_account_id,       "0",    amount), # CR income acct
            ]
            bank_line_num = 1

        bank_line_id = 0
        for lnum, acct_id, dr, cr in lines:
            c2 = self._conn.execute(
                """
                INSERT INTO journal_entry_lines
                    (journal_entry_id, line_number, account_id, debit_amount, credit_amount)
                VALUES (?, ?, ?, ?, ?)
                """,
                (je_id, lnum, acct_id, dr, cr),
            )
            if lnum == bank_line_num:
                bank_line_id = int(c2.lastrowid)  # type: ignore[arg-type]

        return je_id, bank_line_id

    # ── Upload form ───────────────────────────────────────────────────────────

    def render_upload_form(
        self,
        reconciliation_id: int,
        org: dict,
        theme: str,
        error: str | None = None,
    ) -> PageResponse:
        recon = self._get_recon(reconciliation_id)
        if not recon:
            return PageResponse(404, render_template("error.html", {
                "org": org, "theme": theme,
                "heading": "Not Found",
                "message": "Reconciliation not found.",
                "page_key": "reconciliations",
            }))
        if recon["status"] != "OPEN":
            return PageResponse(400, render_template("error.html", {
                "org": org, "theme": theme,
                "heading": "Reconciliation Finalized",
                "message": "Cannot import into a finalized reconciliation.",
                "page_key": "reconciliations",
            }))
        pending = self._get_pending_batch(reconciliation_id)
        return self._render(
            "bank_statement_upload.html",
            org=org, theme=theme,
            page_key="reconciliations",
            recon=recon,
            bank_account=None,
            pending=pending,
            error=error,
            upload_action=None,
            cancel_url=None,
        )

    # ── Handle file upload → store PENDING → redirect ─────────────────────────

    def handle_upload(
        self,
        reconciliation_id: int,
        file_bytes: bytes,
        filename: str,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        recon = self._get_recon(reconciliation_id)
        if not recon or recon["status"] != "OPEN":
            resp = self.render_upload_form(reconciliation_id, org, theme,
                                           error="Reconciliation not found or not open.")
            return None, resp

        # Drop any existing PENDING batch before creating the new one
        self._conn.execute(
            "DELETE FROM bank_import_batches WHERE reconciliation_id = ? AND status = 'PENDING'",
            (reconciliation_id,),
        )
        self._conn.commit()

        try:
            file_format = detect_format(file_bytes)
        except ParseError as e:
            return None, self.render_upload_form(reconciliation_id, org, theme, error=str(e))

        if file_format == "OFX":
            try:
                transactions = parse_ofx(file_bytes)
            except Exception as exc:
                return None, self.render_upload_form(
                    reconciliation_id, org, theme,
                    error=f"Could not read OFX file: {exc}",
                )
            csv_col_map: dict = {}
            map_is_usable = True
        else:
            try:
                transactions, _headers, csv_col_map = parse_csv(file_bytes)
            except Exception as exc:
                return None, self.render_upload_form(
                    reconciliation_id, org, theme,
                    error=f"Could not read CSV file: {exc}",
                )
            map_is_usable = csv_map_is_usable(csv_col_map)
            if not map_is_usable:
                transactions = []

        gl_lines = self._get_uncleared_lines(reconciliation_id)
        rules = self._load_rules()

        batch_id = self._store_pending_batch(
            reconciliation_id=reconciliation_id,
            bank_account_id=int(recon["bank_account_id"]),
            filename=filename,
            file_format=file_format,
            file_bytes=file_bytes,
            csv_col_map=csv_col_map,
            transactions=transactions,
            gl_lines=gl_lines,
            rules=rules,
        )

        return f"/reconciliations/{reconciliation_id}/import-statement/{batch_id}", None

    # ── Batch preview (reads from DB) ─────────────────────────────────────────

    def render_batch_preview(
        self,
        reconciliation_id: int,
        batch_id: int,
        org: dict,
        theme: str,
        error: str | None = None,
    ) -> PageResponse:
        recon = self._get_recon(reconciliation_id)
        if not recon:
            return PageResponse(404, render_template("error.html", {
                "org": org, "theme": theme,
                "heading": "Not Found",
                "message": "Reconciliation not found.",
                "page_key": "reconciliations",
            }))

        batch = self._conn.execute(
            """
            SELECT id, source_filename, file_format, transaction_count, matched_count,
                   csv_col_map, status, imported_at
            FROM bank_import_batches
            WHERE id = ? AND reconciliation_id = ?
            """,
            (batch_id, reconciliation_id),
        ).fetchone()
        if not batch:
            return PageResponse(404, render_template("error.html", {
                "org": org, "theme": theme,
                "heading": "Not Found",
                "message": "Import batch not found.",
                "page_key": "reconciliations",
            }))

        txn_rows = self._conn.execute(
            """
            SELECT bt.id, bt.transaction_date, bt.description, bt.memo, bt.amount,
                   bt.transaction_type, bt.matched_line_id, bt.match_type,
                   bt.batch_match_ids, bt.rule_id,
                   r.rule_name, r.action_type, r.default_memo,
                   ra.account_number AS rule_acct_num,
                   ra.account_name   AS rule_acct_name,
                   je.entry_date     AS gl_entry_date,
                   je.memo           AS gl_memo,
                   jel.description   AS gl_line_desc,
                   CAST(jel.debit_amount  AS REAL) AS gl_debit,
                   CAST(jel.credit_amount AS REAL) AS gl_credit
            FROM bank_transactions bt
            LEFT JOIN bank_transaction_rules r  ON r.id  = bt.rule_id
            LEFT JOIN accounts ra               ON ra.id = r.gl_account_id
            LEFT JOIN journal_entry_lines jel   ON jel.id = bt.matched_line_id
            LEFT JOIN journal_entries je        ON je.id  = jel.journal_entry_id
            WHERE bt.import_batch_id = ?
            ORDER BY bt.transaction_date ASC, bt.id ASC
            """,
            (batch_id,),
        ).fetchall()

        # Pre-load batch-match GL line labels
        all_batch_ids: set[int] = set()
        for row in txn_rows:
            if row["match_type"] == "BATCH":
                all_batch_ids.update(json.loads(row["batch_match_ids"] or "[]"))

        batch_line_labels: dict[int, str] = {}
        if all_batch_ids:
            ph = ",".join("?" * len(all_batch_ids))
            bl_rows = self._conn.execute(
                f"""
                SELECT jel.id,
                       je.entry_date, je.memo, jel.description,
                       CAST(jel.debit_amount AS REAL) AS debit_amount
                FROM journal_entry_lines jel
                JOIN journal_entries je ON je.id = jel.journal_entry_id
                WHERE jel.id IN ({ph})
                """,
                list(all_batch_ids),
            ).fetchall()
            for bl in bl_rows:
                label = bl["memo"] or bl["description"] or ""
                batch_line_labels[bl["id"]] = (
                    f"{bl['entry_date']}  {label}  ${bl['debit_amount']:.2f}"
                )

        annotated = []
        for row in txn_rows:
            d = dict(row)
            if d["match_type"] == "BATCH":
                ids = json.loads(d["batch_match_ids"] or "[]")
                d["batch_line_labels"] = [batch_line_labels.get(i, f"line {i}") for i in ids]
            if d["match_type"] == "RULE":
                d["has_period"] = self._period_for_date(d["transaction_date"]) is not None
            annotated.append(d)

        col_map = json.loads(batch["csv_col_map"] or "{}")

        # For CSV: recover headers from stored bytes so remap works
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

        return self._render(
            "bank_statement_preview.html",
            org=org, theme=theme,
            page_key="reconciliations",
            recon=recon,
            batch=batch,
            annotated=annotated,
            counts=counts,
            col_map=col_map,
            headers=headers,
            map_is_usable=(
                csv_map_is_usable(col_map) if col_map else batch["file_format"] == "OFX"
            ),
            error=error,
        )

    # ── Re-map CSV columns (re-parse stored bytes) ────────────────────────────

    def handle_remap(
        self,
        reconciliation_id: int,
        batch_id: int,
        form_data: dict,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        recon = self._get_recon(reconciliation_id)
        if not recon or recon["status"] != "OPEN":
            return f"/reconciliations/{reconciliation_id}/import-statement", None

        fb = self._conn.execute(
            """
            SELECT file_content FROM bank_import_batches
            WHERE id = ? AND reconciliation_id = ? AND status = 'PENDING'
            """,
            (batch_id, reconciliation_id),
        ).fetchone()
        if not fb or not fb["file_content"]:
            resp = self.render_batch_preview(
                reconciliation_id, batch_id, org, theme,
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
            resp = self.render_batch_preview(
                reconciliation_id, batch_id, org, theme,
                error=f"Could not re-parse CSV: {exc}",
            )
            return None, resp

        gl_lines = self._get_uncleared_lines(reconciliation_id)
        rules = self._load_rules()
        bank_account_id = int(recon["bank_account_id"])
        rule_m, gl_m, batch_m = self._compute_matches(
            transactions, gl_lines, rules, bank_account_id=bank_account_id
        )
        match_count = len(rule_m) + len(gl_m) + len(batch_m)

        self._conn.execute(
            "DELETE FROM bank_transactions WHERE import_batch_id = ?", (batch_id,)
        )

        for i, txn in enumerate(transactions):
            if i in rule_m:
                match_type = "RULE"; matched_line_id = None
                rule_id = rule_m[i]["id"]; batch_ids = "[]"
            elif i in gl_m:
                match_type = "GL"; matched_line_id = gl_m[i]
                rule_id = None; batch_ids = "[]"
            elif i in batch_m:
                match_type = "BATCH"; matched_line_id = None
                rule_id = None; batch_ids = json.dumps(batch_m[i])
            else:
                match_type = "UNMATCHED"; matched_line_id = None
                rule_id = None; batch_ids = "[]"

            self._conn.execute(
                """
                INSERT INTO bank_transactions
                    (bank_account_id, import_batch_id, transaction_date,
                     description, memo, amount, external_reference,
                     transaction_type, matched_line_id, reconciliation_status,
                     match_type, batch_match_ids, rule_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bank_account_id, batch_id,
                    txn.transaction_date.isoformat(),
                    txn.description, txn.memo, str(txn.amount),
                    txn.fitid, txn.transaction_type,
                    matched_line_id,
                    "UNMATCHED" if match_type == "UNMATCHED" else "MATCHED",
                    match_type, batch_ids, rule_id,
                ),
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

        return f"/reconciliations/{reconciliation_id}/import-statement/{batch_id}", None

    def handle_reapply_rules(
        self,
        reconciliation_id: int,
        batch_id: int,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        """Re-run rule/GL matching against stored file content without re-uploading."""
        recon = self._get_recon(reconciliation_id)
        if not recon or recon["status"] != "OPEN":
            return f"/reconciliations/{reconciliation_id}/import-statement", None

        fb = self._conn.execute(
            "SELECT file_content, file_format, csv_col_map FROM bank_import_batches WHERE id = ? AND reconciliation_id = ?",
            (batch_id, reconciliation_id),
        ).fetchone()
        if not fb or not fb["file_content"]:
            resp = self.render_batch_preview(reconciliation_id, batch_id, org, theme,
                                             error="File data not found — please re-upload.")
            return None, resp

        file_format = fb["file_format"] or detect_format(fb["file_content"])
        if file_format == "OFX":
            last4 = recon["account_last4"] or ""
            sections = parse_ofx_by_account(fb["file_content"])
            transactions = []
            for acctid, txns in sections:
                if not last4 or acctid.endswith(last4):
                    transactions = txns
                    break
            if not transactions and sections:
                transactions = sections[0][1]
            resolved_col_map: dict = {}
        else:
            col_map = json.loads(fb["csv_col_map"] or "{}")
            transactions, _headers, resolved_col_map = parse_csv(fb["file_content"], col_map or None)

        bank_account_id = int(recon["bank_account_id"])
        gl_lines = self._get_uncleared_lines(reconciliation_id)
        rules = self._load_rules()
        rule_m, gl_m, batch_m = self._compute_matches(
            transactions, gl_lines, rules, bank_account_id=bank_account_id
        )
        match_count = len(rule_m) + len(gl_m) + len(batch_m)

        self._conn.execute("DELETE FROM bank_transactions WHERE import_batch_id = ?", (batch_id,))

        for i, txn in enumerate(transactions):
            if i in rule_m:
                match_type = "RULE"; matched_line_id = None
                rule_id = rule_m[i]["id"]; batch_ids = "[]"
            elif i in gl_m:
                match_type = "GL"; matched_line_id = gl_m[i]
                rule_id = None; batch_ids = "[]"
            elif i in batch_m:
                match_type = "BATCH"; matched_line_id = None
                rule_id = None; batch_ids = json.dumps(batch_m[i])
            else:
                match_type = "UNMATCHED"; matched_line_id = None
                rule_id = None; batch_ids = "[]"

            self._conn.execute(
                """
                INSERT INTO bank_transactions
                    (bank_account_id, import_batch_id, transaction_date,
                     description, memo, amount, external_reference,
                     transaction_type, matched_line_id, reconciliation_status,
                     match_type, batch_match_ids, rule_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bank_account_id, batch_id,
                    txn.transaction_date.isoformat(),
                    txn.description, txn.memo, str(txn.amount),
                    txn.fitid, txn.transaction_type,
                    matched_line_id,
                    "UNMATCHED" if match_type == "UNMATCHED" else "MATCHED",
                    match_type, batch_ids, rule_id,
                ),
            )

        self._conn.execute(
            "UPDATE bank_import_batches SET transaction_count = ?, matched_count = ? WHERE id = ?",
            (len(transactions), match_count, batch_id),
        )
        self._conn.commit()
        return f"/reconciliations/{reconciliation_id}/import-statement/{batch_id}", None

    # ── Apply: create JEs, clear reconciliation lines, mark APPLIED ───────────

    def handle_apply(
        self,
        reconciliation_id: int,
        batch_id: int,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        recon = self._get_recon(reconciliation_id)
        if not recon or recon["status"] != "OPEN":
            return f"/reconciliations/{reconciliation_id}", None

        batch = self._conn.execute(
            "SELECT id FROM bank_import_batches WHERE id = ? AND reconciliation_id = ? AND status = 'PENDING'",
            (batch_id, reconciliation_id),
        ).fetchone()
        if not batch:
            return f"/reconciliations/{reconciliation_id}", None

        txn_rows = self._conn.execute(
            """
            SELECT bt.id, bt.transaction_date, bt.description, bt.memo, bt.amount,
                   bt.matched_line_id, bt.match_type, bt.batch_match_ids, bt.rule_id,
                   r.action_type, r.gl_account_id, r.lot_id, r.default_memo
            FROM bank_transactions bt
            LEFT JOIN bank_transaction_rules r ON r.id = bt.rule_id
            WHERE bt.import_batch_id = ?
            """,
            (batch_id,),
        ).fetchall()

        bank_gl_account_id = int(recon["gl_account_id"])
        matched_count = 0

        for txn in txn_rows:
            mt = txn["match_type"]

            if mt == "RULE" and txn["rule_id"] and txn["gl_account_id"]:
                period_id = self._period_for_date(txn["transaction_date"])
                if not period_id:
                    continue
                je_id, bank_line_id = self._create_rule_je(
                    dict(txn), dict(txn), bank_gl_account_id, period_id
                )
                self._conn.execute(
                    "INSERT OR IGNORE INTO reconciliation_clears (reconciliation_id, journal_entry_line_id) VALUES (?, ?)",
                    (reconciliation_id, bank_line_id),
                )
                self._conn.execute(
                    "UPDATE bank_transactions SET created_je_id = ? WHERE id = ?",
                    (je_id, txn["id"]),
                )
                # Record AR payment if this is a dues rule with a specific lot
                if txn["action_type"] == "dues_payment" and txn["lot_id"]:
                    amount = abs(Decimal(str(txn["amount"])))
                    self._record_ar_payment(
                        lot_id=int(txn["lot_id"]),
                        je_id=je_id,
                        bank_account_id=int(recon["bank_account_id"]),
                        amount=amount,
                        txn_date=txn["transaction_date"],
                        description=txn["default_memo"] or txn["description"] or "",
                    )
                matched_count += 1

            elif mt == "GL" and txn["matched_line_id"]:
                self._conn.execute(
                    "INSERT OR IGNORE INTO reconciliation_clears (reconciliation_id, journal_entry_line_id) VALUES (?, ?)",
                    (reconciliation_id, txn["matched_line_id"]),
                )
                matched_count += 1

            elif mt == "BATCH":
                ids = json.loads(txn["batch_match_ids"] or "[]")
                for line_id in ids:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO reconciliation_clears (reconciliation_id, journal_entry_line_id) VALUES (?, ?)",
                        (reconciliation_id, line_id),
                    )
                if ids:
                    matched_count += 1

        self._conn.execute(
            "UPDATE bank_import_batches SET status = 'APPLIED' WHERE id = ?",
            (batch_id,),
        )
        self._conn.commit()

        total = len(txn_rows)
        msg = f"{matched_count}+of+{total}+bank+transactions+matched+and+pre-checked."
        return f"/reconciliations/{reconciliation_id}?msg={msg}", None

    # ── Delete pending batch ──────────────────────────────────────────────────

    def handle_delete(
        self,
        reconciliation_id: int,
        batch_id: int,
    ) -> str:
        self._conn.execute(
            "DELETE FROM bank_import_batches WHERE id = ? AND reconciliation_id = ? AND status = 'PENDING'",
            (batch_id, reconciliation_id),
        )
        self._conn.commit()
        return f"/reconciliations/{reconciliation_id}/import-statement"

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
        """Account-agnostic upload: OFX routes by ACCTID, CSV uses the selected account."""
        def _err(msg: str) -> tuple[None, PageResponse]:
            return None, self.render_agnostic_upload_form(org, theme, error=msg)

        try:
            file_format = detect_format(file_bytes)
        except ParseError as e:
            return _err(str(e))

        rules = self._load_rules()

        if file_format == "OFX":
            try:
                account_sections = parse_ofx_by_account(file_bytes)
            except Exception as exc:
                return _err(f"Could not read OFX file: {exc}")

            created: list[tuple[int, int, str]] = []
            skipped: list[str] = []

            for acctid, transactions in account_sections:
                last4 = acctid[-4:] if acctid else ""
                row = self._conn.execute(
                    "SELECT id, account_name FROM bank_accounts WHERE account_last4 = ?", (last4,)
                ).fetchone() if last4 else None

                if row is None:
                    skipped.append(acctid or "(no ACCTID)")
                    continue

                batch_id = self._store_pending_batch(
                    reconciliation_id=None,
                    bank_account_id=int(row["id"]),
                    filename=filename, file_format=file_format,
                    file_bytes=file_bytes, csv_col_map={},
                    transactions=transactions, gl_lines=[], rules=rules,
                )
                created.append((batch_id, int(row["id"]), row["account_name"]))

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

        else:
            # CSV — need an account selected
            if not csv_bank_account_id:
                return _err("Please select which bank account this CSV is for.")
            ba = self._get_bank_account(csv_bank_account_id)
            if not ba:
                return _err("Selected bank account not found.")
            try:
                transactions, _headers, csv_col_map = parse_csv(file_bytes)
            except Exception as exc:
                return _err(f"Could not read CSV file: {exc}")
            if not csv_map_is_usable(csv_col_map):
                transactions = []
            batch_id = self._store_pending_batch(
                reconciliation_id=None,
                bank_account_id=csv_bank_account_id,
                filename=filename, file_format=file_format,
                file_bytes=file_bytes, csv_col_map=csv_col_map,
                transactions=transactions, gl_lines=[], rules=rules,
            )
            msg = f"Imported {len(transactions)} transactions into {ba['account_name']}."
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
        gl_lines: list[dict] = []

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
                    gl_lines=gl_lines,
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
                gl_lines=gl_lines,
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
                   ra.account_number AS rule_acct_num,
                   ra.account_name   AS rule_acct_name,
                   je.entry_date     AS gl_entry_date,
                   je.memo           AS gl_memo,
                   jel.description   AS gl_line_desc,
                   CAST(jel.debit_amount  AS REAL) AS gl_debit,
                   CAST(jel.credit_amount AS REAL) AS gl_credit
            FROM bank_transactions bt
            LEFT JOIN bank_transaction_rules r  ON r.id  = bt.rule_id
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
        gl_lines: list[dict] = []
        rule_m, gl_m, batch_m = self._compute_matches(
            transactions, gl_lines, rules, bank_account_id=bank_account_id
        )
        match_count = len(rule_m) + len(gl_m) + len(batch_m)

        self._conn.execute(
            "DELETE FROM bank_transactions WHERE import_batch_id = ?", (batch_id,)
        )

        for i, txn in enumerate(transactions):
            if i in rule_m:
                match_type = "RULE"; matched_line_id = None
                rule_id = rule_m[i]["id"]; batch_ids = "[]"
            elif i in gl_m:
                match_type = "GL"; matched_line_id = gl_m[i]
                rule_id = None; batch_ids = "[]"
            elif i in batch_m:
                match_type = "BATCH"; matched_line_id = None
                rule_id = None; batch_ids = json.dumps(batch_m[i])
            else:
                match_type = "UNMATCHED"; matched_line_id = None
                rule_id = None; batch_ids = "[]"

            self._conn.execute(
                """
                INSERT INTO bank_transactions
                    (bank_account_id, import_batch_id, transaction_date,
                     description, memo, amount, external_reference,
                     transaction_type, matched_line_id, reconciliation_status,
                     match_type, batch_match_ids, rule_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bank_account_id, batch_id,
                    txn.transaction_date.isoformat(),
                    txn.description, txn.memo, str(txn.amount),
                    txn.fitid, txn.transaction_type,
                    matched_line_id,
                    "UNMATCHED" if match_type == "UNMATCHED" else "MATCHED",
                    match_type, batch_ids, rule_id,
                ),
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

    def handle_standalone_reapply(
        self,
        bank_account_id: int,
        batch_id: int,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        """Re-run rule matching against stored file content (no GL lines in standalone mode)."""
        ba = self._get_bank_account(bank_account_id)
        if not ba:
            return f"/bank-accounts/{bank_account_id}/import-statement", None

        fb = self._conn.execute(
            "SELECT file_content, file_format, csv_col_map FROM bank_import_batches WHERE id = ? AND bank_account_id = ? AND reconciliation_id IS NULL",
            (batch_id, bank_account_id),
        ).fetchone()
        if not fb or not fb["file_content"]:
            resp = self.render_standalone_batch_preview(bank_account_id, batch_id, org, theme,
                                                        error="File data not found — please re-upload.")
            return None, resp

        file_format = fb["file_format"] or detect_format(fb["file_content"])
        if file_format == "OFX":
            # Filter to only transactions for this batch's account using ACCTID last-4
            last4 = ba["account_last4"] or ""
            sections = parse_ofx_by_account(fb["file_content"])
            transactions = []
            for acctid, txns in sections:
                if not last4 or acctid.endswith(last4):
                    transactions = txns
                    break
            if not transactions and sections:
                transactions = sections[0][1]  # fallback
            resolved_col_map: dict = {}
        else:
            col_map = json.loads(fb["csv_col_map"] or "{}")
            transactions, _headers, resolved_col_map = parse_csv(fb["file_content"], col_map or None)

        rules = self._load_rules()
        gl_lines: list[dict] = []
        rule_m, gl_m, batch_m = self._compute_matches(
            transactions, gl_lines, rules, bank_account_id=bank_account_id
        )
        match_count = len(rule_m) + len(gl_m) + len(batch_m)

        self._conn.execute("DELETE FROM bank_transactions WHERE import_batch_id = ?", (batch_id,))

        for i, txn in enumerate(transactions):
            if i in rule_m:
                match_type = "RULE"; matched_line_id = None
                rule_id = rule_m[i]["id"]; batch_ids = "[]"
            elif i in gl_m:
                match_type = "GL"; matched_line_id = gl_m[i]
                rule_id = None; batch_ids = "[]"
            elif i in batch_m:
                match_type = "BATCH"; matched_line_id = None
                rule_id = None; batch_ids = json.dumps(batch_m[i])
            else:
                match_type = "UNMATCHED"; matched_line_id = None
                rule_id = None; batch_ids = "[]"

            self._conn.execute(
                """
                INSERT INTO bank_transactions
                    (bank_account_id, import_batch_id, transaction_date,
                     description, memo, amount, external_reference,
                     transaction_type, matched_line_id, reconciliation_status,
                     match_type, batch_match_ids, rule_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bank_account_id, batch_id,
                    txn.transaction_date.isoformat(),
                    txn.description, txn.memo, str(txn.amount),
                    txn.fitid, txn.transaction_type,
                    matched_line_id,
                    "UNMATCHED" if match_type == "UNMATCHED" else "MATCHED",
                    match_type, batch_ids, rule_id,
                ),
            )

        self._conn.execute(
            "UPDATE bank_import_batches SET transaction_count = ?, matched_count = ? WHERE id = ?",
            (len(transactions), match_count, batch_id),
        )
        self._conn.commit()
        return f"/bank-accounts/{bank_account_id}/import-statement/{batch_id}", None

    def handle_standalone_apply(
        self,
        bank_account_id: int,
        batch_id: int,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        """Create JEs for rule-matched transactions; skip reconciliation line clearing."""
        ba = self._get_bank_account(bank_account_id)
        if not ba:
            return f"/bank-accounts/{bank_account_id}/import-statement", None

        batch = self._conn.execute(
            "SELECT id FROM bank_import_batches WHERE id = ? AND bank_account_id = ? AND reconciliation_id IS NULL AND status = 'PENDING'",
            (batch_id, bank_account_id),
        ).fetchone()
        if not batch:
            return f"/bank-accounts/{bank_account_id}/import-statement", None

        bank_gl_account_id = int(ba["gl_account_id"])

        txn_rows = self._conn.execute(
            """
            SELECT bt.id, bt.transaction_date, bt.description, bt.memo, bt.amount,
                   bt.matched_line_id, bt.match_type, bt.batch_match_ids, bt.rule_id,
                   r.action_type, r.gl_account_id, r.lot_id, r.default_memo
            FROM bank_transactions bt
            LEFT JOIN bank_transaction_rules r ON r.id = bt.rule_id
            WHERE bt.import_batch_id = ?
            """,
            (batch_id,),
        ).fetchall()

        for txn in txn_rows:
            mt = txn["match_type"]

            if mt == "RULE" and txn["rule_id"] and txn["gl_account_id"]:
                period_id = self._period_for_date(txn["transaction_date"])
                if not period_id:
                    continue
                je_id, _bank_line_id = self._create_rule_je(
                    dict(txn), dict(txn), bank_gl_account_id, period_id
                )
                self._conn.execute(
                    "UPDATE bank_transactions SET created_je_id = ? WHERE id = ?",
                    (je_id, txn["id"]),
                )
                # Record AR payment if this is a dues rule with a specific lot
                if txn["action_type"] == "dues_payment" and txn["lot_id"]:
                    amount = abs(Decimal(str(txn["amount"])))
                    self._record_ar_payment(
                        lot_id=int(txn["lot_id"]),
                        je_id=je_id,
                        bank_account_id=bank_account_id,
                        amount=amount,
                        txn_date=txn["transaction_date"],
                        description=txn["default_memo"] or txn["description"] or "",
                    )

        self._conn.execute(
            "UPDATE bank_import_batches SET status = 'APPLIED' WHERE id = ?",
            (batch_id,),
        )
        self._conn.commit()

        return f"/bank-accounts/{bank_account_id}/import-statement?applied={batch_id}", None

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
                SELECT p.id, p.receipt_number, p.payment_date,
                       CAST(p.amount AS REAL) AS amount, p.payment_method,
                       o.display_name AS owner_name,
                       l.lot_number
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

            # Collect text from rule-matched transactions in this batch to detect
            # owners whose payments are already handled by a rule.
            rule_texts: list[str] = []
            for r in self._conn.execute(
                "SELECT description, memo FROM bank_transactions "
                "WHERE import_batch_id = ? AND match_type = 'RULE'",
                (batch_id,),
            ):
                if r["description"]: rule_texts.append(r["description"].lower())
                if r["memo"]: rule_texts.append(r["memo"].lower())

            # Text from the current OFX transaction itself.
            curr_texts = [t.lower() for t in (ofx_desc, ofx_memo) if t]

            for c in candidates:
                name = (c["owner_name"] or "").lower()
                # Use meaningful tokens (skip very short words)
                tokens = [p for p in name.split() if len(p) > 2]
                c["rule_handled"] = bool(tokens and any(
                    tok in txt for tok in tokens for txt in rule_texts
                ))
                c["in_description"] = bool(tokens and any(
                    tok in txt for tok in tokens for txt in curr_texts
                ))
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
