"""Rule-engine tests for ``apply_rules``.

Drives the matcher against fixture OFX rows + rule dicts. The intent is
to nail down the contract that has bitten us several times:

  * description_contains is matched against ``txn.description`` ONLY (not
    memo) — case-insensitive substring.
  * match_memo is matched against ``txn.memo`` ONLY.
  * match_type is matched against ``txn.transaction_type`` (e.g. "CREDIT"
    vs "DEBIT" in OFX 1.x).
  * match_amount is an exact-magnitude check (±$0.01).
  * bank_account_id, when set, restricts the rule to that account.
  * Rule order matters — first match wins.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from hoa_accounting.web.bank_statement_import import (
    ParsedTransaction,
    apply_rules,
)


def _txn(
    *,
    description: str = "",
    memo: str = "",
    amount: str = "0.00",
    transaction_type: str = "",
) -> ParsedTransaction:
    return ParsedTransaction(
        transaction_date=date(2026, 1, 15),
        amount=Decimal(amount),
        description=description,
        memo=memo,
        fitid="FITID-1",
        transaction_type=transaction_type,
    )


def _rule(**kwargs):
    """Build a rule dict with sensible defaults."""
    base = {
        "id": kwargs.pop("id", 1),
        "rule_name": kwargs.pop("rule_name", "TestRule"),
        "active_flag": 1,
        "description_contains": "",
        "match_memo": "",
        "match_type": "",
        "match_amount": "",
        "bank_account_id": None,
        "action_type": "direct_expense",
    }
    base.update(kwargs)
    return base


# ── description_contains ───────────────────────────────────────────────


def test_desc_substring_match_caseinsensitive():
    rules = [_rule(description_contains="OmniSite")]
    assert 0 in apply_rules([_txn(description="OMNISITE BILLPAY")], rules)


def test_desc_no_match_is_skipped():
    rules = [_rule(description_contains="Acme")]
    assert apply_rules([_txn(description="OmniSite")], rules) == {}


def test_desc_does_not_match_against_memo():
    """Common bug: rule wanted 'Interest' but only the memo had it."""
    rules = [_rule(description_contains="Interest")]
    txn = _txn(description="", memo="IOD Interest Payment")
    assert apply_rules([txn], rules) == {}


# ── match_memo ────────────────────────────────────────────────────────


def test_memo_substring_match_caseinsensitive():
    rules = [_rule(match_memo="iod interest")]
    assert 0 in apply_rules([_txn(memo="IOD Interest Payment")], rules)


def test_memo_does_not_match_against_description():
    rules = [_rule(match_memo="Interest")]
    assert apply_rules([_txn(description="Interest", memo="")], rules) == {}


# ── match_type ────────────────────────────────────────────────────────


def test_type_credit_matches_credit():
    rules = [_rule(match_type="CREDIT")]
    assert 0 in apply_rules([_txn(transaction_type="CREDIT")], rules)


def test_type_dep_does_not_match_credit():
    """Common bug: rules built for 'DEP' don't match OFX 'CREDIT'."""
    rules = [_rule(match_type="DEP")]
    assert apply_rules([_txn(transaction_type="CREDIT")], rules) == {}


# ── match_amount ──────────────────────────────────────────────────────


def test_amount_exact_match():
    rules = [_rule(match_amount="155.06")]
    assert 0 in apply_rules([_txn(amount="155.06")], rules)


def test_amount_within_one_cent_matches():
    """Tolerance is ±$0.01 inclusive — bank rounding shouldn't reject."""
    rules = [_rule(match_amount="155.06")]
    assert 0 in apply_rules([_txn(amount="155.07")], rules)


def test_amount_two_cents_off_does_not_match():
    rules = [_rule(match_amount="155.06")]
    assert apply_rules([_txn(amount="155.08")], rules) == {}


def test_amount_negative_matches_positive_target():
    """Owner check vs vendor debit — ``apply_rules`` compares magnitudes."""
    rules = [_rule(match_amount="100.00")]
    assert 0 in apply_rules([_txn(amount="-100.00")], rules)


# ── bank_account_id scoping ────────────────────────────────────────────


def test_rule_scoped_to_other_account_skipped():
    rules = [_rule(bank_account_id=2, description_contains="X")]
    txn = _txn(description="X")
    assert apply_rules([txn], rules, bank_account_id=1) == {}


def test_rule_scoped_to_matching_account_fires():
    rules = [_rule(bank_account_id=1, description_contains="X")]
    txn = _txn(description="X")
    assert 0 in apply_rules([txn], rules, bank_account_id=1)


def test_rule_with_no_account_scope_fires_for_any_account():
    rules = [_rule(bank_account_id=None, description_contains="X")]
    txn = _txn(description="X")
    assert 0 in apply_rules([txn], rules, bank_account_id=42)


# ── active_flag ───────────────────────────────────────────────────────


def test_inactive_rule_does_not_fire():
    rules = [_rule(active_flag=0, description_contains="X")]
    assert apply_rules([_txn(description="X")], rules) == {}


# ── AND semantics across criteria ──────────────────────────────────────


def test_all_set_criteria_must_match():
    """Description matches but type doesn't → no match."""
    rules = [_rule(description_contains="Sanchez", match_type="CREDIT")]
    txn = _txn(description="Fabian Sanchez", transaction_type="DEBIT")
    assert apply_rules([txn], rules) == {}


def test_unset_criterion_is_ignored():
    """Empty fields are wildcards; only set fields constrain matching."""
    rules = [_rule()]  # everything blank
    assert 0 in apply_rules([_txn(description="anything")], rules)


# ── First-match-wins ───────────────────────────────────────────────────


def test_first_matching_rule_wins():
    rules = [
        _rule(id=10, rule_name="Generic", description_contains="Bill"),
        _rule(id=20, rule_name="Specific", description_contains="Acme Bill"),
    ]
    matches = apply_rules([_txn(description="Acme Bill")], rules)
    assert (
        matches[0]["id"] == 10
    )  # generic first → wins despite "Specific" being a tighter fit


def test_more_specific_rule_first_takes_precedence():
    rules = [
        _rule(id=20, rule_name="Specific", description_contains="Acme Bill"),
        _rule(id=10, rule_name="Generic", description_contains="Bill"),
    ]
    matches = apply_rules([_txn(description="Acme Bill")], rules)
    assert matches[0]["id"] == 20
