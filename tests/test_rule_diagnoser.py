"""Tests for the rule diagnoser — per-criterion match results + suggestions."""

from __future__ import annotations

from hoa_accounting.services.rule_diagnoser import diagnose, find_other_matches


def _txn(**kw):
    base = {
        "description": "",
        "memo": "",
        "amount": "0.00",
        "transaction_type": "",
        "bank_account_id": 1,
    }
    base.update(kw)
    return base


def _rule(**kw):
    base = {
        "id": 1,
        "rule_name": "R",
        "active_flag": 1,
        "description_contains": "",
        "match_memo": "",
        "match_type": "",
        "match_amount": "",
        "bank_account_id": None,
    }
    base.update(kw)
    return base


def test_full_match_all_criteria_pass():
    txn = _txn(
        description="OmniSite",
        memo="My Frost Billpay",
        amount="-152.00",
        transaction_type="DEBIT",
    )
    r = diagnose(
        _rule(
            description_contains="OmniSite",
            match_type="DEBIT",
            match_amount="152.00",
            bank_account_id=1,
        ),
        txn,
    )
    assert r.would_match is True
    assert all(c.passed for c in r.checks)


def test_description_in_memo_only_suggests_match_memo():
    """Common bug — user put 'Interest' in description_contains but the
    bank only puts it in memo. Diagnoser should hint at match_memo."""
    txn = _txn(memo="IOD Interest Payment", transaction_type="CREDIT", amount="11.68")
    r = diagnose(_rule(description_contains="Interest"), txn)
    assert r.would_match is False
    failed = [c for c in r.checks if not c.passed]
    assert any("memo" in c.suggestion.lower() for c in failed)


def test_dep_vs_credit_type_mismatch_gets_specific_hint():
    txn = _txn(transaction_type="CREDIT", amount="100")
    r = diagnose(_rule(match_type="DEP"), txn)
    assert r.would_match is False
    bad = [c for c in r.checks if c.name == "match_type" and not c.passed][0]
    assert "CREDIT" in bad.suggestion


def test_account_scope_mismatch_explained():
    txn = _txn(bank_account_id=1)
    r = diagnose(_rule(bank_account_id=2, description_contains="X"), txn)
    assert r.would_match is False
    failed = [c for c in r.checks if c.name == "bank_account_id"]
    assert failed and not failed[0].passed
    assert "bank #2" in failed[0].detail


def test_inactive_rule_flagged_even_when_criteria_match():
    txn = _txn(description="X")
    r = diagnose(_rule(description_contains="X", active_flag=0), txn)
    assert r.would_match is False
    assert any(c.name == "active_flag" and not c.passed for c in r.checks)


def test_amount_within_tolerance_passes():
    txn = _txn(amount="155.07")
    r = diagnose(_rule(match_amount="155.06"), txn)
    assert r.would_match is True


def test_amount_outside_tolerance_fails():
    txn = _txn(amount="155.10")
    r = diagnose(_rule(match_amount="155.06"), txn)
    assert r.would_match is False


def test_unparseable_amount_target_reported():
    txn = _txn(amount="100")
    r = diagnose(_rule(match_amount="five hundred"), txn)
    assert r.would_match is False
    assert any("could not be parsed" in c.detail for c in r.checks)


def test_find_other_matches_lists_collisions():
    txn = _txn(description="Acme Bill", transaction_type="DEBIT")
    rules = [
        _rule(id=10, rule_name="Generic", description_contains="Bill"),
        _rule(id=20, rule_name="Acme", description_contains="Acme"),
        _rule(id=30, rule_name="Unrelated", description_contains="Foo"),
    ]
    others = find_other_matches(rules, txn, exclude_rule_id=20)
    names = {r.rule_name for r in others}
    assert names == {"Generic"}
    assert all(r.would_match for r in others)
