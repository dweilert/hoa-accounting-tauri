"""Real-world OFX fixture tests.

Drives the OFX parser, multi-account splitter, and ``OFXAdapter`` against
a full-year MS Money export from Frost Bank (2025, 152 transactions
across two checking accounts). The synthetic snippets in
``test_bank_ingest.py`` cover the parsing branches; this file pins the
real-bank shape so a regression in the wild gets caught.

The fixture is committed to the repo. It is **test data only** —
``batch_pdf``-style ingest into the live DB would create out-of-balance
conditions; tests here parse the bytes in memory and never write.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from hoa_accounting.web.bank_ingest import (
    CanonicalBankTxn,
    OFXAdapter,
    normalize_trn_type,
)
from hoa_accounting.web.bank_statement_import import (
    detect_format,
    parse_ofx,
    parse_ofx_by_account,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ofx" / "MSMoney-All-2025.ofx"


@pytest.fixture(scope="module")
def ofx_bytes() -> bytes:
    return FIXTURE.read_bytes()


# ── Format detection ─────────────────────────────────────────────────────


def test_detect_format_identifies_ofx(ofx_bytes: bytes) -> None:
    assert detect_format(ofx_bytes) == "OFX"


def test_ofx_adapter_detects_with_full_confidence(ofx_bytes: bytes) -> None:
    assert OFXAdapter().detect(ofx_bytes) == 1.0


# ── Single-pass parse ────────────────────────────────────────────────────


def test_parse_ofx_returns_all_152_transactions(ofx_bytes: bytes) -> None:
    txns = parse_ofx(ofx_bytes)
    assert len(txns) == 152


def test_parse_ofx_date_range_spans_full_year(ofx_bytes: bytes) -> None:
    txns = parse_ofx(ofx_bytes)
    dates = [t.transaction_date for t in txns]
    assert min(dates) == date(2025, 1, 7)
    assert max(dates) == date(2025, 12, 31)


def test_parse_ofx_total_amount_matches_file(ofx_bytes: bytes) -> None:
    """Sum of TRNAMT across both accounts (raw signed sum)."""
    txns = parse_ofx(ofx_bytes)
    total = sum((t.amount for t in txns), Decimal("0"))
    assert total == Decimal("14115.20")


def test_parse_ofx_extracts_fitid_and_type(ofx_bytes: bytes) -> None:
    txns = parse_ofx(ofx_bytes)
    # Every Frost row carries a FITID and TRNTYPE.
    assert all(t.fitid for t in txns)
    raw_types = {t.transaction_type for t in txns}
    assert raw_types == {"CHECK", "CREDIT", "DEBIT", "DEP"}


# ── Multi-account split ──────────────────────────────────────────────────


def test_parse_ofx_by_account_finds_two_accounts(ofx_bytes: bytes) -> None:
    by_acct = parse_ofx_by_account(ofx_bytes)
    acctids = {acctid for acctid, _ in by_acct}
    assert acctids == {"591201421", "585717264"}


def test_parse_ofx_by_account_per_account_counts(ofx_bytes: bytes) -> None:
    by_acct = dict(parse_ofx_by_account(ofx_bytes))
    assert len(by_acct["591201421"]) == 125
    assert len(by_acct["585717264"]) == 27
    # Sum across accounts equals the single-pass count.
    assert sum(len(v) for v in by_acct.values()) == 152


# ── Canonical adapter pipeline ───────────────────────────────────────────


def test_ofx_adapter_produces_canonical_records(ofx_bytes: bytes) -> None:
    canon = OFXAdapter().parse(ofx_bytes)
    assert len(canon) == 152
    assert all(isinstance(c, CanonicalBankTxn) for c in canon)


def test_ofx_adapter_normalizes_dep_to_credit(ofx_bytes: bytes) -> None:
    """OFX 'DEP' (deposit) collapses to canonical 'CREDIT'."""
    canon = OFXAdapter().parse(ofx_bytes)
    types = {c.transaction_type for c in canon}
    # 'DEP' must not leak past the adapter boundary.
    assert "DEP" not in types
    assert types <= {"DEBIT", "CREDIT", "CHECK"}
    # Each input TRNTYPE folds into exactly the expected canonical bucket.
    assert normalize_trn_type("DEP") == "CREDIT"


def test_canonical_dedup_key_is_stable(ofx_bytes: bytes) -> None:
    """Re-parsing the same file twice yields identical dedup keys.

    Catches the classic regression where a non-deterministic field (a
    timestamp, dict ordering, etc.) sneaks into the fingerprint.
    """
    a = OFXAdapter().parse(ofx_bytes)
    b = OFXAdapter().parse(ofx_bytes)
    keys_a = [t.dedup_key(bank_account_id=1) for t in a]
    keys_b = [t.dedup_key(bank_account_id=1) for t in b]
    assert keys_a == keys_b


def test_canonical_dedup_key_varies_by_bank_account(ofx_bytes: bytes) -> None:
    canon = OFXAdapter().parse(ofx_bytes)
    one = canon[0].dedup_key(bank_account_id=1)
    two = canon[0].dedup_key(bank_account_id=2)
    assert one != two
