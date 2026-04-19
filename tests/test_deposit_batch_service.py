"""Tests for the deposit-batch posting service.

Exercise the service against a real migrated in-memory DB so the 0003
schema changes (dropped UNIQUE, deposit_batches table, deposit_batch_id
column) are actually in place and the consolidated-JE shape is
verified.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.exceptions import ValidationError
from hoa_accounting.services.deposit_batch_service import DepositRow
from hoa_accounting.services.factory import ServiceFactory


# ── Test scaffolding ────────────────────────────────────────────────


def _seed(conn: sqlite3.Connection) -> dict[str, int]:
    """Seed the minimum reference data needed to post a deposit batch.

    Returns a dict of id labels → row ids so the tests can reference
    seeded owners / lots / accounts by readable names.
    """
    conn.executemany(
        "INSERT INTO accounting_periods "
        "(id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES (?, ?, ?, ?, ?, ?, 0)",
        [
            (1, "2026-01", "2026-01-01", "2026-01-31", 2026, 1),
            (2, "2026-02", "2026-02-01", "2026-02-28", 2026, 2),
            (3, "2026-03", "2026-03-01", "2026-03-31", 2026, 3),
            (4, "2026-04", "2026-04-01", "2026-04-30", 2026, 4),
            (5, "2026-05", "2026-05-01", "2026-05-31", 2026, 5),
        ],
    )
    # Owner-AR control account and a cash account (both assets).
    conn.execute(
        "INSERT INTO accounts "
        "(id, account_number, account_name, account_type_id, fund_code, "
        " is_bank_account, is_active) "
        "VALUES (1000, '1000', 'Cash - Operating', 1, 'OPERATING', 1, 1)"
    )
    conn.execute(
        "INSERT INTO accounts "
        "(id, account_number, account_name, account_type_id, fund_code, "
        " is_bank_account, is_active) "
        "VALUES (1100, '1100', 'Accounts Receivable - Owners', 1, 'OPERATING', 0, 1)"
    )
    # Assessment income for later when we seed assessments.
    conn.execute(
        "INSERT INTO accounts "
        "(id, account_number, account_name, account_type_id, fund_code, "
        " is_bank_account, is_active) "
        "VALUES (4000, '4000', 'Assessment Income', 4, 'OPERATING', 0, 1)"
    )
    # Bank account wrapping the cash GL.
    conn.execute(
        "INSERT INTO bank_accounts "
        "(id, account_name, institution_name, account_last4, account_type, "
        " gl_account_id, active_flag) "
        "VALUES (1, 'Operating Checking', 'Big Bank', '1234', 'CHECKING', 1000, 1)"
    )
    # Two owners, two lots, two current primary-contact ownerships.
    conn.execute(
        "INSERT INTO owners (id, owner_type, display_name, active_flag) "
        "VALUES (1, 'PERSON', 'Alice Park', 1), "
        "       (2, 'PERSON', 'Bob Cole', 1)"
    )
    conn.execute(
        "INSERT INTO lots (id, lot_number, active_flag) "
        "VALUES (1, 'L-1', 1), (2, 'L-2', 1)"
    )
    conn.execute(
        "INSERT INTO lot_ownership "
        "(id, lot_id, owner_id, start_date, end_date) "
        "VALUES (1, 1, 1, '2020-01-01', NULL), "
        "       (2, 2, 2, '2021-01-01', NULL)"
    )
    conn.commit()
    return {
        "bank_account_id": 1,
        "cash_account_id": 1000,
        "ar_account_id": 1100,
        "income_account_id": 4000,
        "alice_owner_id": 1,
        "bob_owner_id": 2,
        "alice_lot_id": 1,
        "bob_lot_id": 2,
    }


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    Migrator().apply_all(c)
    return c


# ── Consolidated JE shape ───────────────────────────────────────────


def test_batch_creates_one_je_with_one_debit_and_n_credits(conn: sqlite3.Connection) -> None:
    """Core accounting shape: 1 debit to cash for total, N AR credits for each payment."""
    ids = _seed(conn)
    factory = ServiceFactory(conn)

    result = factory.deposit_batch_service().post_batch(
        deposit_date="2026-04-15",
        bank_account_id=ids["bank_account_id"],
        receivable_account_id=ids["ar_account_id"],
        notes="April batch 1",
        rows=[
            DepositRow(lot_id=ids["alice_lot_id"], amount="200.00",
                       reference_number="1234"),
            DepositRow(lot_id=ids["bob_lot_id"], amount="150.00",
                       reference_number="1235", memo="partial"),
        ],
    )

    # Two payments, one JE, three lines: 1 debit + 2 credits.
    lines = conn.execute(
        """
        SELECT account_id, debit_amount, credit_amount, owner_id
        FROM journal_entry_lines
        WHERE journal_entry_id = ?
        ORDER BY line_number
        """,
        (result.journal_entry_id,),
    ).fetchall()
    assert len(lines) == 3
    assert int(lines[0]["account_id"]) == ids["cash_account_id"]
    assert Decimal(str(lines[0]["debit_amount"])) == Decimal("350.00")
    assert Decimal(str(lines[0]["credit_amount"])) == Decimal("0.00")
    # The two AR credits are against the AR account, with owner ids attached.
    ar_lines = lines[1:]
    for ln in ar_lines:
        assert int(ln["account_id"]) == ids["ar_account_id"]
        assert Decimal(str(ln["debit_amount"])) == Decimal("0.00")
    ar_credits = sum(Decimal(str(ln["credit_amount"])) for ln in ar_lines)
    assert ar_credits == Decimal("350.00")
    # Owner ids land on the AR lines.
    owners = {int(ln["owner_id"]) for ln in ar_lines}
    assert owners == {ids["alice_owner_id"], ids["bob_owner_id"]}


def test_batch_inserts_payments_and_batch_row(conn: sqlite3.Connection) -> None:
    """Two payments share one JE; the batch row points at both."""
    ids = _seed(conn)
    factory = ServiceFactory(conn)
    result = factory.deposit_batch_service().post_batch(
        deposit_date="2026-04-15",
        bank_account_id=ids["bank_account_id"],
        receivable_account_id=ids["ar_account_id"],
        rows=[
            DepositRow(lot_id=ids["alice_lot_id"], amount="200.00",
                       reference_number="1234"),
            DepositRow(lot_id=ids["bob_lot_id"], amount="150.00",
                       reference_number="1235"),
        ],
    )

    # Batch row.
    batch = conn.execute(
        "SELECT deposit_date, total_amount, journal_entry_id FROM deposit_batches WHERE id = ?",
        (result.deposit_batch_id,),
    ).fetchone()
    assert batch["deposit_date"] == "2026-04-15"
    assert Decimal(str(batch["total_amount"])) == Decimal("350.00")
    assert int(batch["journal_entry_id"]) == result.journal_entry_id

    # Payments linked to the same JE and the same batch.
    rows = conn.execute(
        "SELECT owner_id, amount, journal_entry_id, deposit_batch_id, reference_number "
        "FROM payments WHERE deposit_batch_id = ? ORDER BY id",
        (result.deposit_batch_id,),
    ).fetchall()
    assert len(rows) == 2
    for r in rows:
        assert int(r["journal_entry_id"]) == result.journal_entry_id
        assert int(r["deposit_batch_id"]) == result.deposit_batch_id
    assert {r["reference_number"] for r in rows} == {"1234", "1235"}


# ── Auto-apply to oldest open assessments ──────────────────────────


def _post_assessment(factory: ServiceFactory, *, lot_id: int, owner_id: int,
                     amount: str, due_date: str, description: str) -> int:
    """Helper: post an assessment via the existing service."""
    result = factory.assessment_service().post_assessment(
        entry_date=due_date,
        lot_id=lot_id,
        owner_id=owner_id,
        amount=amount,
        description=description,
        receivable_account_id=1100,
        income_account_id=4000,
        due_date=due_date,
    )
    return result.assessment_id


def test_payment_auto_applies_to_oldest_open_assessment(conn: sqlite3.Connection) -> None:
    """A $200 payment with a $200 outstanding assessment fully pays it (PAID)."""
    ids = _seed(conn)
    factory = ServiceFactory(conn)

    assessment_id = _post_assessment(
        factory,
        lot_id=ids["alice_lot_id"],
        owner_id=ids["alice_owner_id"],
        amount="200.00",
        due_date="2026-04-01",
        description="Annual assessment 2026",
    )

    factory.deposit_batch_service().post_batch(
        deposit_date="2026-04-15",
        bank_account_id=ids["bank_account_id"],
        receivable_account_id=ids["ar_account_id"],
        rows=[DepositRow(lot_id=ids["alice_lot_id"], amount="200.00",
                         reference_number="1234")],
    )

    # The assessment flips to PAID.
    row = conn.execute(
        "SELECT status FROM assessments WHERE id = ?", (assessment_id,)
    ).fetchone()
    assert row["status"] == "PAID"

    # payment_applications has exactly one row for the 200.
    apps = conn.execute(
        "SELECT applied_amount FROM payment_applications WHERE assessment_id = ?",
        (assessment_id,),
    ).fetchall()
    assert len(apps) == 1
    assert Decimal(str(apps[0]["applied_amount"])) == Decimal("200.00")


def test_partial_payment_marks_assessment_partial(conn: sqlite3.Connection) -> None:
    ids = _seed(conn)
    factory = ServiceFactory(conn)
    assessment_id = _post_assessment(
        factory,
        lot_id=ids["alice_lot_id"],
        owner_id=ids["alice_owner_id"],
        amount="200.00",
        due_date="2026-04-01",
        description="Annual",
    )
    factory.deposit_batch_service().post_batch(
        deposit_date="2026-04-15",
        bank_account_id=ids["bank_account_id"],
        receivable_account_id=ids["ar_account_id"],
        rows=[DepositRow(lot_id=ids["alice_lot_id"], amount="75.00",
                         reference_number="2001")],
    )
    row = conn.execute(
        "SELECT status FROM assessments WHERE id = ?", (assessment_id,)
    ).fetchone()
    assert row["status"] == "PARTIAL"


def test_payment_flows_across_multiple_assessments_oldest_first(conn: sqlite3.Connection) -> None:
    """A $250 payment against $100 old + $100 newer + $200 newest pays old two in full,
    partial on the third."""
    ids = _seed(conn)
    factory = ServiceFactory(conn)
    a_old = _post_assessment(factory, lot_id=ids["alice_lot_id"],
                             owner_id=ids["alice_owner_id"], amount="100.00",
                             due_date="2026-02-01", description="Feb")
    a_mid = _post_assessment(factory, lot_id=ids["alice_lot_id"],
                             owner_id=ids["alice_owner_id"], amount="100.00",
                             due_date="2026-03-01", description="Mar")
    a_new = _post_assessment(factory, lot_id=ids["alice_lot_id"],
                             owner_id=ids["alice_owner_id"], amount="200.00",
                             due_date="2026-04-01", description="Apr")

    factory.deposit_batch_service().post_batch(
        deposit_date="2026-04-20",
        bank_account_id=ids["bank_account_id"],
        receivable_account_id=ids["ar_account_id"],
        rows=[DepositRow(lot_id=ids["alice_lot_id"], amount="250.00",
                         reference_number="3001")],
    )

    statuses = dict(conn.execute(
        "SELECT id, status FROM assessments WHERE owner_id = ?",
        (ids["alice_owner_id"],),
    ).fetchall())
    assert statuses[a_old] == "PAID"
    assert statuses[a_mid] == "PAID"
    assert statuses[a_new] == "PARTIAL"


def test_payment_with_no_outstanding_assessments_is_prepayment(conn: sqlite3.Connection) -> None:
    """A payment with nothing owed creates no applications (becomes a credit balance)."""
    ids = _seed(conn)
    factory = ServiceFactory(conn)
    factory.deposit_batch_service().post_batch(
        deposit_date="2026-04-15",
        bank_account_id=ids["bank_account_id"],
        receivable_account_id=ids["ar_account_id"],
        rows=[DepositRow(lot_id=ids["alice_lot_id"], amount="50.00",
                         reference_number="4001")],
    )
    apps = conn.execute("SELECT COUNT(*) c FROM payment_applications").fetchone()
    assert apps["c"] == 0


# ── Validation ──────────────────────────────────────────────────────


def test_empty_batch_rejected(conn: sqlite3.Connection) -> None:
    ids = _seed(conn)
    factory = ServiceFactory(conn)
    with pytest.raises(ValidationError, match="at least one"):
        factory.deposit_batch_service().post_batch(
            deposit_date="2026-04-15",
            bank_account_id=ids["bank_account_id"],
            receivable_account_id=ids["ar_account_id"],
            rows=[],
        )


def test_lot_without_current_owner_rejected(conn: sqlite3.Connection) -> None:
    """A lot with no open lot_ownership row can't receive a payment."""
    ids = _seed(conn)
    # Add a lot without any ownership row.
    conn.execute(
        "INSERT INTO lots (id, lot_number, active_flag) VALUES (3, 'L-VACANT', 1)"
    )
    conn.commit()
    factory = ServiceFactory(conn)
    with pytest.raises(ValidationError, match="no current primary-contact owner"):
        factory.deposit_batch_service().post_batch(
            deposit_date="2026-04-15",
            bank_account_id=ids["bank_account_id"],
            receivable_account_id=ids["ar_account_id"],
            rows=[DepositRow(lot_id=3, amount="100.00")],
        )


def test_non_positive_amount_rejected(conn: sqlite3.Connection) -> None:
    ids = _seed(conn)
    factory = ServiceFactory(conn)
    with pytest.raises(ValidationError, match="greater than zero"):
        factory.deposit_batch_service().post_batch(
            deposit_date="2026-04-15",
            bank_account_id=ids["bank_account_id"],
            receivable_account_id=ids["ar_account_id"],
            rows=[DepositRow(lot_id=ids["alice_lot_id"], amount="0.00")],
        )


def test_batch_is_atomic(conn: sqlite3.Connection) -> None:
    """If any row fails validation, nothing persists."""
    ids = _seed(conn)
    factory = ServiceFactory(conn)
    before_je = conn.execute("SELECT COUNT(*) c FROM journal_entries").fetchone()["c"]
    before_pay = conn.execute("SELECT COUNT(*) c FROM payments").fetchone()["c"]
    before_batch = conn.execute("SELECT COUNT(*) c FROM deposit_batches").fetchone()["c"]

    with pytest.raises(ValidationError):
        factory.deposit_batch_service().post_batch(
            deposit_date="2026-04-15",
            bank_account_id=ids["bank_account_id"],
            receivable_account_id=ids["ar_account_id"],
            rows=[
                DepositRow(lot_id=ids["alice_lot_id"], amount="100.00"),
                DepositRow(lot_id=999, amount="50.00"),  # nonexistent lot
            ],
        )

    assert conn.execute("SELECT COUNT(*) c FROM journal_entries").fetchone()["c"] == before_je
    assert conn.execute("SELECT COUNT(*) c FROM payments").fetchone()["c"] == before_pay
    assert conn.execute("SELECT COUNT(*) c FROM deposit_batches").fetchone()["c"] == before_batch
