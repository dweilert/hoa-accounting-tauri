"""Rule engine driven against the real-world Frost Bank OFX fixture.

The synthetic cases in ``test_rule_engine.py`` cover branches in
isolation; this file pins behavior on a full-year file so a regression
that silently re-categorizes hundreds of real bank lines is caught.

All counts are derived from the 2025 export (152 transactions across
two accounts).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hoa_accounting.web.bank_statement_import import (
    apply_rules,
    parse_ofx,
    parse_ofx_by_account,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ofx" / "MSMoney-All-2025.ofx"


@pytest.fixture(scope="module")
def txns():
    return parse_ofx(FIXTURE.read_bytes())


def _rule(**kw):
    """Default-active rule dict matching the bank_transaction_rules row shape."""
    base = {
        "id": kw.pop("id", 1),
        "rule_name": kw.pop("rule_name", "test"),
        "active_flag": 1,
        "category_id": 100,
        "description_contains": "",
        "match_memo": "",
        "match_type": "",
        "match_amount": "",
    }
    base.update(kw)
    return base


# ── Single-criterion matching ───────────────────────────────────────────


def test_description_rule_matches_all_fabian_sanchez_payments(txns) -> None:
    """16 bill-pay rows to Fabian Sanchez should map to a single rule."""
    matches = apply_rules(txns, [_rule(description_contains="Fabian Sanchez")])
    assert len(matches) == 16


def test_memo_rule_matches_all_teller_deposits(txns) -> None:
    """58 teller-deposit memos drive the dominant deposit category."""
    matches = apply_rules(txns, [_rule(match_memo="Teller Deposit")])
    assert len(matches) == 58


def test_memo_rule_matches_iod_interest(txns) -> None:
    """12 monthly interest postings — important because misclassifying
    these inflates income on the dashboard."""
    matches = apply_rules(txns, [_rule(match_memo="IOD Interest Payment")])
    assert len(matches) == 12


def test_description_rule_matches_city_of_austin(txns) -> None:
    """City of Austin shows up 12× as a utility debit."""
    matches = apply_rules(txns, [_rule(description_contains="City of Austin")])
    assert len(matches) == 12


def test_type_rule_isolates_check_payments(txns) -> None:
    """Only 3 checks in the file — TRNTYPE is CHECK on each."""
    matches = apply_rules(txns, [_rule(match_type="CHECK")])
    assert len(matches) == 3


# ── Combined criteria (AND logic) ────────────────────────────────────────


def test_description_and_memo_combined(txns) -> None:
    """Internal account transfers carry both a 'FROM ACCOUNT' description
    and an 'Internet Fund Transfer' memo — combining lets us route them
    to TRANSFER without dragging in unrelated billpay credits."""
    matches = apply_rules(
        txns,
        [
            _rule(
                description_contains="FROM ACCOUNT",
                match_memo="Internet Fund Transfer",
            )
        ],
    )
    assert len(matches) == 12


def test_amount_match_finds_recurring_360_billpay(txns) -> None:
    """Fabian Sanchez has 16 billpay lines but only 5 are exactly $360.00.
    The amount predicate narrows the description match to those 5."""
    matches = apply_rules(
        txns,
        [_rule(description_contains="Fabian Sanchez", match_amount="360.00")],
    )
    assert len(matches) == 5
    for idx in matches:
        assert abs(txns[idx].amount) == 360


# ── Rule precedence ──────────────────────────────────────────────────────


def test_first_matching_rule_wins(txns) -> None:
    """Rule order is authoritative — the engine never scans further once
    a match is found, so a broad rule placed before a narrow one will
    swallow the narrow rule's hits."""
    broad = _rule(id=1, rule_name="any-debit", match_type="DEBIT", category_id=999)
    narrow = _rule(
        id=2,
        rule_name="city-utilities",
        description_contains="City of Austin",
        category_id=42,
    )
    matches = apply_rules(txns, [broad, narrow])
    # All 12 City of Austin rows are DEBIT, so broad wins them.
    austin = [
        i for i, t in enumerate(txns) if "city of austin" in t.description.lower()
    ]
    assert len(austin) == 12
    for i in austin:
        assert matches[i]["id"] == 1


def test_narrow_rule_first_protects_from_broad_match(txns) -> None:
    """Inverse of the above — putting the specific rule first preserves it."""
    narrow = _rule(
        id=2,
        rule_name="city-utilities",
        description_contains="City of Austin",
        category_id=42,
    )
    broad = _rule(id=1, rule_name="any-debit", match_type="DEBIT", category_id=999)
    matches = apply_rules(txns, [narrow, broad])
    austin_hits = [m for m in matches.values() if m["id"] == 2]
    assert len(austin_hits) == 12


def test_inactive_rule_is_skipped(txns) -> None:
    rules = [
        _rule(id=1, description_contains="Fabian Sanchez", active_flag=0),
        _rule(id=2, description_contains="Fabian Sanchez", active_flag=1),
    ]
    matches = apply_rules(txns, rules)
    # Every match comes from rule 2 — rule 1 was bypassed despite being first.
    assert len(matches) == 16
    assert all(m["id"] == 2 for m in matches.values())


# ── Per-account scoping ──────────────────────────────────────────────────


def test_account_scoped_rule_does_not_fire_on_other_account() -> None:
    """A rule pinned to bank_account_id=591201421 must not match lines
    parsed from the 585717264 statement — the second account holds 27
    rows of similar memo text and we don't want cross-pollination."""
    by_acct = dict(parse_ofx_by_account(FIXTURE.read_bytes()))
    other_acct_txns = by_acct["585717264"]

    pinned = _rule(
        rule_name="op-only",
        match_memo="Teller Deposit",
        bank_account_id=591201421,  # the *other* account
    )
    # apply_rules is told the txns it's seeing belong to 585717264:
    matches = apply_rules(other_acct_txns, [pinned], bank_account_id=585717264)
    assert matches == {}


def test_account_scoped_rule_fires_on_its_own_account() -> None:
    by_acct = dict(parse_ofx_by_account(FIXTURE.read_bytes()))
    op_txns = by_acct["591201421"]
    pinned = _rule(
        rule_name="op-only",
        match_memo="Teller Deposit",
        bank_account_id=591201421,
    )
    matches = apply_rules(op_txns, [pinned], bank_account_id=591201421)
    # All 58 teller-deposit rows live on the operating account.
    assert len(matches) == 58


# ── Skip-indices honored ─────────────────────────────────────────────────


def test_skip_indices_excludes_already_matched_rows(txns) -> None:
    """Caller can mark indices to bypass — used after a 1-to-1 match
    against open invoices, so the rule pass doesn't re-categorize them."""
    austin_rule = _rule(description_contains="City of Austin")
    full = apply_rules(txns, [austin_rule])
    pre_skip = set(list(full.keys())[:5])
    partial = apply_rules(txns, [austin_rule], skip_indices=pre_skip)
    assert pre_skip.isdisjoint(partial.keys())
    assert len(partial) == len(full) - len(pre_skip)
