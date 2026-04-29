"""Diagnose why a transaction rule does or doesn't match a bank row.

The matcher in :mod:`hoa_accounting.web.bank_statement_import.apply_rules`
is opaque — it returns the first rule that fully matches, or nothing.
This module mirrors its logic with verbose per-criterion output so the
UI can tell the user *why* a rule failed and what to change.

Two kinds of result:

* :class:`CriterionCheck` — one specific filter on a rule, with whether
  it passed and a fix-it hint when it didn't.
* :class:`MatchReport` — the rule-level verdict plus all the criterion
  checks. ``would_match`` is the bottom line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class CriterionCheck:
    name: str
    passed: bool
    detail: str
    suggestion: str = ""


@dataclass
class MatchReport:
    rule_id: int | None
    rule_name: str
    would_match: bool
    checks: list[CriterionCheck] = field(default_factory=list)


# A "transaction-like" record. Accepts dict, sqlite Row, or an object with
# the right attribute names — the diagnoser just reads via ``_get``.
def _get(obj: Any, key: str, default: Any = "") -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    if hasattr(obj, "keys"):
        try:
            return obj[key] if key in obj.keys() else default
        except Exception:
            pass
    return getattr(obj, key, default)


def diagnose(rule: dict[str, Any], txn: Any) -> MatchReport:
    """Apply each criterion on ``rule`` to ``txn`` and report.

    Returns a :class:`MatchReport`. ``would_match`` is True only when
    every set criterion passed AND the rule is active.
    """
    name = str(rule.get("rule_name") or f"Rule {rule.get('id', '?')}")
    checks: list[CriterionCheck] = []

    # 0. active_flag — a soft check; inactive rules can still be diagnosed.
    if int(rule.get("active_flag", 1)) == 0:
        checks.append(
            CriterionCheck(
                "active_flag",
                False,
                "Rule is inactive — it will not run during ingest.",
                "Set Active = Yes on the rule.",
            )
        )

    # 1. bank_account_id scoping
    rule_ba = rule.get("bank_account_id")
    txn_ba = _get(txn, "bank_account_id")
    if rule_ba:
        if txn_ba and int(txn_ba) == int(rule_ba):
            checks.append(
                CriterionCheck(
                    "bank_account_id",
                    True,
                    f"Rule scoped to bank #{rule_ba}; transaction is on the same account.",
                )
            )
        else:
            checks.append(
                CriterionCheck(
                    "bank_account_id",
                    False,
                    f"Rule is scoped to bank #{rule_ba}; "
                    f"transaction is on bank #{txn_ba or '?'}.",
                    "Either change the rule's Bank Account to match, "
                    "or clear it to apply to all accounts.",
                )
            )

    # 2. description_contains
    desc_pat = str(rule.get("description_contains") or "").strip()
    txn_desc = str(_get(txn, "description") or "")
    if desc_pat:
        if desc_pat.lower() in txn_desc.lower():
            checks.append(
                CriterionCheck(
                    "description_contains",
                    True,
                    f"Description {txn_desc!r} contains {desc_pat!r}.",
                )
            )
        else:
            sug = (
                f"The transaction's description is {txn_desc!r}. "
                f"If the substring you really want is in the memo "
                f"({_get(txn, 'memo')!r}), use Match Memo instead. "
                f"Otherwise broaden or fix the description filter."
            )
            checks.append(
                CriterionCheck(
                    "description_contains",
                    False,
                    f"Description {txn_desc!r} does not contain {desc_pat!r}.",
                    sug,
                )
            )

    # 3. match_memo
    memo_pat = str(rule.get("match_memo") or "").strip()
    txn_memo = str(_get(txn, "memo") or "")
    if memo_pat:
        if memo_pat.lower() in txn_memo.lower():
            checks.append(
                CriterionCheck(
                    "match_memo",
                    True,
                    f"Memo {txn_memo!r} contains {memo_pat!r}.",
                )
            )
        else:
            checks.append(
                CriterionCheck(
                    "match_memo",
                    False,
                    f"Memo {txn_memo!r} does not contain {memo_pat!r}.",
                    "Try a shorter substring; banks vary on the memo wording.",
                )
            )

    # 4. match_type — substring of transaction_type
    type_pat = str(rule.get("match_type") or "").strip()
    txn_type = str(_get(txn, "transaction_type") or "")
    if type_pat:
        if type_pat.lower() in txn_type.lower():
            checks.append(
                CriterionCheck(
                    "match_type",
                    True,
                    f"Type {txn_type!r} matches {type_pat!r}.",
                )
            )
        else:
            sug = ""
            if type_pat.upper() == "DEP" and txn_type.upper() == "CREDIT":
                sug = (
                    "OFX 1.x typically writes deposits as 'CREDIT', "
                    "not 'DEP'. Change the rule's Type to 'CREDIT'."
                )
            elif type_pat.upper() == "CHK" and txn_type.upper() == "CHECK":
                sug = "Use 'CHECK' (the OFX wording) instead of 'CHK'."
            else:
                sug = (
                    f"Set Type to {txn_type!r}, or clear it to match "
                    f"any transaction type."
                )
            checks.append(
                CriterionCheck(
                    "match_type",
                    False,
                    f"Type {txn_type!r} does not match {type_pat!r}.",
                    sug,
                )
            )

    # 5. match_amount — magnitude ±$0.01
    amount_pat = str(rule.get("match_amount") or "").strip()
    if amount_pat:
        try:
            target = abs(Decimal(amount_pat.lstrip("$").replace(",", "")))
            actual = abs(Decimal(str(_get(txn, "amount") or "0")))
            if abs(actual - target) <= Decimal("0.01"):
                checks.append(
                    CriterionCheck(
                        "match_amount",
                        True,
                        f"Amount {actual} matches target {target} (±$0.01).",
                    )
                )
            else:
                checks.append(
                    CriterionCheck(
                        "match_amount",
                        False,
                        f"Amount {actual} differs from target {target} by "
                        f"${abs(actual - target)}.",
                        "Either correct the rule's Match Amount or clear it.",
                    )
                )
        except (InvalidOperation, ValueError):
            checks.append(
                CriterionCheck(
                    "match_amount",
                    False,
                    f"Match Amount {amount_pat!r} could not be parsed as a number.",
                    "Use a plain number like 155.06 (no currency symbol needed).",
                )
            )

    is_active = int(rule.get("active_flag", 1)) == 1
    all_ok = all(c.passed for c in checks)
    would = (
        is_active
        and all_ok
        and any(
            # at least ONE criterion must be set; an all-blank rule is a wildcard
            rule.get(k)
            for k in (
                "description_contains",
                "match_memo",
                "match_type",
                "match_amount",
                "bank_account_id",
            )
        )
    )
    # If no criteria are set the rule is a wildcard that fires on every row
    # for its account. Reflect that.
    if not any(
        rule.get(k)
        for k in ("description_contains", "match_memo", "match_type", "match_amount")
    ):
        if not rule.get("bank_account_id") or (
            txn_ba and int(rule["bank_account_id"]) == int(txn_ba)
        ):
            would = is_active

    return MatchReport(
        rule_id=int(rule["id"]) if rule.get("id") is not None else None,
        rule_name=name,
        would_match=would,
        checks=checks,
    )


def find_other_matches(
    rules: list[dict[str, Any]],
    txn: Any,
    *,
    exclude_rule_id: int | None = None,
) -> list[MatchReport]:
    """Return every rule (other than ``exclude_rule_id``) that ALSO matches.

    Useful for spotting rule-order collisions — if two rules both match
    the same row, only the first in the catalog will fire at ingest time.
    """
    out: list[MatchReport] = []
    for r in rules:
        if exclude_rule_id is not None and r.get("id") == exclude_rule_id:
            continue
        report = diagnose(r, txn)
        if report.would_match:
            out.append(report)
    return out
