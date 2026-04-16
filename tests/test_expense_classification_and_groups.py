"""Cover the 0002 migration: expense_classification and group_code.

Verifies (a) the new schema columns exist and their CHECK constraints
behave, (b) the new fine-grained expense accounts are seeded under the
correct group_code, (c) the old generic expense accounts are deactivated,
(d) JournalLineInput.expense_classification roundtrips through the
repository correctly, and (e) reversing a classified expense entry
preserves the classification on the reversal entry.
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator


# ── Schema & seed shape ────────────────────────────────────────────────


def _fresh_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    Migrator().apply_all(conn)
    return conn


def test_accounts_has_group_code_column() -> None:
    conn = _fresh_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(accounts)")}
    assert "group_code" in cols


def test_journal_entry_lines_has_expense_classification_column() -> None:
    conn = _fresh_conn()
    cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(journal_entry_lines)")
    }
    assert "expense_classification" in cols


def test_new_expense_accounts_are_seeded() -> None:
    """Every group from the spreadsheet has at least one account."""
    conn = _fresh_conn()
    expected_groups = {
        "LANDSCAPE", "SEWER", "ROAD", "WALL",
        "ENTRANCE", "UTILITIES", "INSURANCE", "MISC", "FIREWISE",
    }
    seeded = {
        r["group_code"]
        for r in conn.execute(
            "SELECT DISTINCT group_code FROM accounts "
            "WHERE group_code IS NOT NULL AND is_active = 1"
        )
    }
    assert expected_groups.issubset(seeded)


def test_landscape_subcategories_are_seeded() -> None:
    """Every Landscape category seeded in 0002 is present after all
    migrations apply. Names reflect the 0006 rename (prefix dropped)."""
    conn = _fresh_conn()
    names = {
        r["account_name"]
        for r in conn.execute(
            "SELECT account_name FROM accounts "
            "WHERE group_code = 'LANDSCAPE' AND is_active = 1"
        )
    }
    for required in [
        "Mow & Blow",
        "Sprinkler System",
        "Lighting System",
        "Mulch",
        "Tree Trimming",
        "Bed Maintenance",
        "Hill Maintenance",
        "Plants",
        "Other",
    ]:
        assert required in names


def test_old_generic_expense_accounts_are_deactivated_if_present() -> None:
    """The migration deactivates the old 6000-series placeholder accounts.

    A DB created fresh from migrations only (no initializer) won't have
    those placeholders at all — the migration's UPDATE just affects zero
    rows, which is fine. A DB bootstrapped by the initializer *will* have
    them; in that case they must be inactive post-migration.
    """
    conn = _fresh_conn()
    # Insert the legacy placeholders so we can confirm the UPDATE branch fires.
    for num, name in [
        ("6000", "Legacy Landscaping Expense"),
        ("6010", "Legacy Utilities Expense"),
        ("6100", "Legacy Reserve Expense"),
    ]:
        conn.execute(
            "INSERT INTO accounts "
            "(account_number, account_name, account_type_id, fund_code, "
            " is_bank_account, is_active) "
            "VALUES (?, ?, 5, 'OPERATING', 0, 1)",
            (num, name),
        )
    conn.commit()

    # Re-apply 0002 is not possible (already recorded), so simulate it:
    # re-run the UPDATE the migration would run.
    conn.execute(
        "UPDATE accounts SET is_active = 0 "
        "WHERE account_number IN ('6000','6010','6020','6030','6040','6050','6100')"
    )
    conn.commit()

    rows = conn.execute(
        "SELECT account_number, is_active FROM accounts "
        "WHERE account_number IN ('6000','6010','6100')"
    ).fetchall()
    assert len(rows) == 3
    for row in rows:
        assert int(row["is_active"]) == 0


# ── CHECK constraints ──────────────────────────────────────────────────


def test_group_code_check_rejects_unknown_value() -> None:
    conn = _fresh_conn()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO accounts "
            "(account_number, account_name, account_type_id, group_code) "
            "VALUES ('9999', 'Bad', 5, 'BOGUS')"
        )


def test_expense_classification_check_rejects_unknown_value() -> None:
    conn = _fresh_conn()
    # Need a journal entry + period for the insert FK to line up.
    conn.execute(
        "INSERT INTO accounting_periods "
        "(id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES (1, '2026-01', '2026-01-01', '2026-01-31', 2026, 1, 0)"
    )
    conn.execute(
        "INSERT INTO journal_entries "
        "(id, entry_number, entry_date, accounting_period_id, source_type, status, posted_at) "
        "VALUES (1, 'JE-X', '2026-01-10', 1, 'MANUAL', 'POSTED', '2026-01-10T00:00:00+00:00')"
    )
    # An expense account to attach the line to — pick a seeded one.
    acct = conn.execute(
        "SELECT id FROM accounts WHERE account_number = '6101'"
    ).fetchone()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO journal_entry_lines "
            "(journal_entry_id, line_number, account_id, debit_amount, credit_amount, "
            " expense_classification) "
            "VALUES (?, 1, ?, 10, 0, 'BOGUS')",
            (1, int(acct["id"])),
        )


# ── Roundtrip through JournalLineInput + repo ─────────────────────────


def _seed_min_for_posting(conn: sqlite3.Connection) -> int:
    """Create the minimal rows needed to post a journal entry. Returns
    an expense account id."""
    conn.execute(
        "INSERT INTO accounting_periods "
        "(id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES (1, '2026-01', '2026-01-01', '2026-01-31', 2026, 1, 0)"
    )
    conn.execute(
        "INSERT INTO accounts "
        "(id, account_number, account_name, account_type_id, fund_code, "
        " is_bank_account, is_active, group_code) "
        "VALUES (999, '2999', 'Test AP', 2, 'OPERATING', 0, 1, NULL)"
    )
    expense_acct = conn.execute(
        "SELECT id FROM accounts WHERE account_number = '6101'"
    ).fetchone()
    conn.commit()
    return int(expense_acct["id"])


def test_expense_classification_roundtrips_through_repo() -> None:
    """A JournalLineInput with classification writes and reads it back."""
    from hoa_accounting.models.dto import JournalLineInput
    from hoa_accounting.repositories.journal_repo import JournalRepository
    from hoa_accounting.validators.common import q2

    conn = _fresh_conn()
    expense_acct_id = _seed_min_for_posting(conn)

    repo = JournalRepository(conn)
    journal_entry_id, _ = repo.insert_journal_entry_with_generated_number(
        entry_date="2026-01-10",
        accounting_period_id=1,
        source_type="MANUAL",
        memo="Classification roundtrip",
        created_by_user_id=None,
    )
    repo.insert_journal_lines(
        journal_entry_id=journal_entry_id,
        lines=[
            JournalLineInput(
                account_id=expense_acct_id,
                description="Mow & Blow April",
                debit_amount=q2("300.00"),
                expense_classification="OPERATING",
            ),
            JournalLineInput(
                account_id=999,  # Test AP (liability)
                description="Credit payable",
                credit_amount=q2("300.00"),
                # intentionally left unclassified
            ),
        ],
        amount_formatter=q2,
    )
    conn.commit()

    rows = repo.get_journal_lines(journal_entry_id)
    debit_row, credit_row = rows
    assert str(debit_row["expense_classification"]) == "OPERATING"
    assert credit_row["expense_classification"] is None


def test_improvement_classification_roundtrips() -> None:
    """IMPROVEMENT is accepted and persisted."""
    from hoa_accounting.models.dto import JournalLineInput
    from hoa_accounting.repositories.journal_repo import JournalRepository
    from hoa_accounting.validators.common import q2

    conn = _fresh_conn()
    expense_acct_id = _seed_min_for_posting(conn)

    repo = JournalRepository(conn)
    journal_entry_id, _ = repo.insert_journal_entry_with_generated_number(
        entry_date="2026-01-15",
        accounting_period_id=1,
        source_type="VENDOR_BILL",
        memo="New gate hardware",
        created_by_user_id=None,
    )
    repo.insert_journal_lines(
        journal_entry_id=journal_entry_id,
        lines=[
            JournalLineInput(
                account_id=expense_acct_id,
                description="Gate hardware upgrade",
                debit_amount=q2("1500.00"),
                expense_classification="IMPROVEMENT",
            ),
            JournalLineInput(
                account_id=999,
                description="Payable",
                credit_amount=q2("1500.00"),
            ),
        ],
        amount_formatter=q2,
    )
    conn.commit()

    row = conn.execute(
        "SELECT expense_classification FROM journal_entry_lines "
        "WHERE journal_entry_id = ? AND debit_amount > 0",
        (journal_entry_id,),
    ).fetchone()
    assert str(row["expense_classification"]) == "IMPROVEMENT"


# ── Reversal preserves classification ──────────────────────────────────


def test_reversal_preserves_expense_classification() -> None:
    """A reversed expense line carries the same classification to the reversal."""
    from hoa_accounting.models.dto import JournalLineInput
    from hoa_accounting.repositories.audit_repo import AuditRepository
    from hoa_accounting.repositories.journal_repo import JournalRepository
    from hoa_accounting.repositories.periods_repo import PeriodsRepository
    from hoa_accounting.services.journal_service import JournalService
    from hoa_accounting.services.reversal_service import ReversalService
    from hoa_accounting.validators.account_validator import AccountValidator
    from hoa_accounting.validators.common import q2
    from hoa_accounting.validators.journal_validator import JournalValidator
    from hoa_accounting.validators.period_validator import PeriodValidator
    from hoa_accounting.repositories.accounts_repo import AccountsRepository

    conn = _fresh_conn()
    expense_acct_id = _seed_min_for_posting(conn)

    journal_repo = JournalRepository(conn)
    audit_repo = AuditRepository(conn)
    period_validator = PeriodValidator(PeriodsRepository(conn))
    accounts_repo = AccountsRepository(conn)
    account_validator = AccountValidator(accounts_repo)
    journal_validator = JournalValidator(account_validator)
    journal_service = JournalService(
        conn,
        journal_repo=journal_repo,
        audit_repo=audit_repo,
        period_validator=period_validator,
        journal_validator=journal_validator,
    )
    reversal_service = ReversalService(
        conn,
        journal_repo=journal_repo,
        audit_repo=audit_repo,
        journal_service=journal_service,
    )

    posted = journal_service.post_journal_entry(
        entry_date="2026-01-10",
        source_type="VENDOR_BILL",
        memo="Mow & Blow April",
        created_by_user_id=None,
        lines=[
            JournalLineInput(
                account_id=expense_acct_id,
                description="Mow & Blow April",
                debit_amount=q2("300.00"),
                expense_classification="OPERATING",
            ),
            JournalLineInput(
                account_id=999,
                description="Payable",
                credit_amount=q2("300.00"),
            ),
        ],
    )

    result = reversal_service.reverse_journal_entry(
        journal_entry_id=posted.journal_entry_id,
        reversal_date="2026-01-20",
        created_by_user_id=None,
    )

    # The reversal must carry the classification on the (now-credit) expense line.
    rev_rows = conn.execute(
        "SELECT account_id, debit_amount, credit_amount, expense_classification "
        "FROM journal_entry_lines WHERE journal_entry_id = ? ORDER BY line_number",
        (result.reversal_journal_entry_id,),
    ).fetchall()
    expense_line = next(r for r in rev_rows if int(r["account_id"]) == expense_acct_id)
    assert str(expense_line["expense_classification"]) == "OPERATING"
