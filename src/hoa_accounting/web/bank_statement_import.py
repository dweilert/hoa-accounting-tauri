"""Parse bank statement files: OFX/QFX/QBO and CSV.

No third-party dependencies — uses stdlib only.
"""

from __future__ import annotations

import base64
import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


@dataclass
class ParsedTransaction:
    transaction_date: date
    amount: Decimal          # signed: positive = deposit, negative = payment
    description: str
    memo: str
    fitid: str               # OFX unique ID; '' for CSV
    transaction_type: str    # OFX TRNTYPE (DEBIT/CREDIT/CHECK…); '' for CSV


class ParseError(Exception):
    pass


# ── Format detection ──────────────────────────────────────────────────────────

def detect_format(content: bytes | str) -> str:
    """Return 'OFX' or 'CSV'. Raises ParseError on unrecognized input."""
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    sample = text[:600].upper()
    if "OFXHEADER" in sample or "<OFX>" in sample or "OFXSGML" in sample:
        return "OFX"
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines and "," in lines[0]:
        return "CSV"
    raise ParseError(
        "Unrecognized file format. "
        "Please upload an OFX, QFX, QBO, or CSV file from your bank."
    )


# ── OFX parser ────────────────────────────────────────────────────────────────

def parse_ofx(content: bytes | str) -> list[ParsedTransaction]:
    """Parse OFX 1.x (SGML) or OFX 2.x (XML-like) bank statement files."""
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content

    # Collect STMTTRN blocks.  OFX 2.x uses proper closing tags; OFX 1.x may not.
    blocks = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, re.DOTALL | re.IGNORECASE)
    if not blocks:
        parts = re.split(r"<STMTTRN\b", text, flags=re.IGNORECASE)
        for part in parts[1:]:
            end = re.search(
                r"</BANKTRANLIST>|</STMTRS>|</OFX>|<STMTTRN\b", part, re.IGNORECASE
            )
            blocks.append(part[: end.start()] if end else part)

    transactions: list[ParsedTransaction] = []
    for block in blocks:
        def field(tag: str) -> str:
            m = re.search(r"<" + tag + r">\s*([^\r\n<]+)", block, re.IGNORECASE)
            return m.group(1).strip() if m else ""

        dtposted = field("DTPOSTED")
        trnamt   = field("TRNAMT")
        if not dtposted or not trnamt:
            continue

        date_str = re.sub(r"[^0-9].*$", "", dtposted)[:8]
        try:
            txn_date = datetime.strptime(date_str, "%Y%m%d").date()
        except ValueError:
            continue

        try:
            amount = Decimal(trnamt.replace(",", ""))
        except InvalidOperation:
            continue

        trntype = field("TRNTYPE")
        transactions.append(
            ParsedTransaction(
                transaction_date=txn_date,
                amount=amount,
                description=field("NAME"),
                memo=field("MEMO"),
                fitid=field("FITID"),
                transaction_type=trntype.upper() if trntype else "",
            )
        )

    return transactions


# ── CSV parser ────────────────────────────────────────────────────────────────

_DATE_COLS   = {"date", "transaction date", "trans date", "posted date",
                "posting date", "settlement date", "trans. date", "value date"}
_AMOUNT_COLS = {"amount", "transaction amount", "net amount", "transaction amt", "trans. amount"}
_DEBIT_COLS  = {"debit", "debit amount", "withdrawal", "withdrawals",
                "payment", "charges", "debits", "debit(-)"}
_CREDIT_COLS = {"credit", "credit amount", "deposit", "deposits",
                "credits", "additions", "credit(+)"}
_DESC_COLS   = {"description", "memo", "transaction", "details", "name",
                "payee", "narrative", "transaction detail", "particulars",
                "reference", "transaction description"}

_DATE_FORMATS = [
    "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d/%m/%Y",
    "%m-%d-%Y", "%Y/%m/%d", "%b %d, %Y", "%d %b %Y",
    "%B %d, %Y", "%d-%b-%Y",
]


def _parse_date(s: str) -> date | None:
    s = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def auto_detect_csv_columns(headers: list[str]) -> dict[str, str]:
    """Return column map with keys 'date', 'amount'|('debit','credit'), 'description'."""
    result: dict[str, str] = {}
    for h in headers:
        n = h.lower().strip()
        if n in _DATE_COLS and "date" not in result:
            result["date"] = h
        elif n in _AMOUNT_COLS and "amount" not in result:
            result["amount"] = h
        elif n in _DEBIT_COLS and "debit" not in result:
            result["debit"] = h
        elif n in _CREDIT_COLS and "credit" not in result:
            result["credit"] = h
        elif n in _DESC_COLS and "description" not in result:
            result["description"] = h
    # Single amount column wins over separate debit/credit
    if "amount" in result:
        result.pop("debit", None)
        result.pop("credit", None)
    return result


def _clean_num(s: str) -> str:
    return s.strip().replace(",", "").replace("$", "").replace("(", "-").replace(")", "")


def parse_csv(
    content: bytes | str,
    column_map: dict[str, str] | None = None,
) -> tuple[list[ParsedTransaction], list[str], dict[str, str]]:
    """Parse a CSV bank statement.

    Returns (transactions, headers, resolved_column_map).
    column_map may be None for auto-detection.
    """
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    reader = csv.DictReader(io.StringIO(text))
    headers: list[str] = list(reader.fieldnames or [])
    col = column_map if column_map else auto_detect_csv_columns(headers)

    transactions: list[ParsedTransaction] = []
    for row in reader:
        try:
            txn_date = _parse_date(row.get(col.get("date", ""), ""))
            if txn_date is None:
                continue

            if "amount" in col:
                raw = _clean_num(row.get(col["amount"], ""))
                if not raw:
                    continue
                amount = Decimal(raw)
            elif "debit" in col and "credit" in col:
                dr = _clean_num(row.get(col["debit"], "") or "0")
                cr = _clean_num(row.get(col["credit"], "") or "0")
                amount = (Decimal(cr) if cr else Decimal("0")) - (Decimal(dr) if dr else Decimal("0"))
            else:
                continue

            desc_h = col.get("description", "")
            description = row.get(desc_h, "").strip() if desc_h else ""

            transactions.append(
                ParsedTransaction(
                    transaction_date=txn_date,
                    amount=amount,
                    description=description,
                    memo="",
                    fitid="",
                    transaction_type="",
                )
            )
        except (InvalidOperation, KeyError, TypeError):
            continue

    return transactions, headers, col


def csv_map_is_usable(col: dict[str, str]) -> bool:
    """True if the column map has at least a date and an amount source."""
    has_date   = "date" in col
    has_amount = "amount" in col or ("debit" in col and "credit" in col)
    return has_date and has_amount


# ── Rule matching ────────────────────────────────────────────────────────────

def apply_rules(
    transactions: list[ParsedTransaction],
    rules: list[dict],
    skip_indices: set[int] | None = None,
    bank_account_id: int | None = None,
) -> dict[int, dict]:
    """Return {txn_idx: rule_dict} for the first rule where ALL set criteria match."""
    matches: dict[int, dict] = {}
    for i, txn in enumerate(transactions):
        if skip_indices and i in skip_indices:
            continue
        for rule in rules:
            if not rule.get("active_flag", 1):
                continue
            # Bank account restriction: skip rule if it targets a different account
            rule_ba = rule.get("bank_account_id")
            if rule_ba and bank_account_id and int(rule_ba) != int(bank_account_id):
                continue
            # Each non-empty text/amount criterion must match (AND logic)
            desc_pat = str(rule.get("description_contains", "")).lower().strip()
            if desc_pat and desc_pat not in txn.description.lower():
                continue
            memo_pat = str(rule.get("match_memo", "")).lower().strip()
            if memo_pat and memo_pat not in txn.memo.lower():
                continue
            type_pat = str(rule.get("match_type", "")).lower().strip()
            if type_pat and type_pat not in txn.transaction_type.lower():
                continue
            amount_str = str(rule.get("match_amount", "")).strip()
            if amount_str:
                try:
                    target = abs(Decimal(amount_str.lstrip("$").replace(",", "")))
                    if abs(abs(txn.amount) - target) > Decimal("0.01"):
                        continue
                except Exception:
                    pass
            matches[i] = rule
            break
    return matches


# ── Batch deposit matching (N GL lines → 1 deposit) ──────────────────────────

def _subset_sum(
    items: list[tuple[int, int]],   # (amount_cents, line_id)
    target: int,
    tol: int = 1,
) -> list[int] | None:
    """Backtracking subset-sum with prefix-sum pruning. Returns list of line_ids or None."""
    if not items:
        return None
    items = sorted(items, reverse=True)[:60]   # cap for performance

    # Prefix sums: prefix[i] = sum of items[i:]
    prefix = [0] * len(items)
    prefix[-1] = items[-1][0]
    for k in range(len(items) - 2, -1, -1):
        prefix[k] = prefix[k + 1] + items[k][0]

    found: list[int] | None = None

    def bt(idx: int, remaining: int, chosen: list[int]) -> bool:
        nonlocal found
        if abs(remaining) <= tol:
            found = chosen[:]
            return True
        if idx >= len(items) or remaining < -tol:
            return False
        if prefix[idx] < remaining - tol:          # can't reach target
            return False
        amt, id_ = items[idx]
        if amt <= remaining + tol:                  # include
            chosen.append(id_)
            if bt(idx + 1, remaining - amt, chosen):
                return True
            chosen.pop()
        return bt(idx + 1, remaining, chosen)       # exclude

    bt(0, target, [])
    return found


def find_batch_matches(
    transactions: list[ParsedTransaction],
    gl_lines: list[dict],
    already_matched: set[int],
    skip_indices: set[int] | None = None,
) -> dict[int, list[int]]:
    """For unmatched positive-amount transactions, find groups of GL lines summing to the amount.

    Requires at least 2 GL lines per match (true batch, not a 1:1 that slipped through).
    ±7-day date window, ±$0.01 tolerance.
    """
    used = set(already_matched)
    results: dict[int, list[int]] = {}

    for i, txn in enumerate(transactions):
        if skip_indices and i in skip_indices:
            continue
        if txn.amount <= 0:
            continue                                # deposits only

        target_cents = round(float(txn.amount) * 100)
        candidates: list[tuple[int, int]] = []

        for line in gl_lines:
            if line["line_id"] in used:
                continue
            net = line["debit_amount"] - line["credit_amount"]
            if net < 0.005:
                continue
            try:
                entry_date = datetime.strptime(line["entry_date"], "%Y-%m-%d").date()
            except ValueError:
                continue
            if abs((entry_date - txn.transaction_date).days) <= 7:
                candidates.append((round(net * 100), line["line_id"]))

        if len(candidates) < 2:
            continue

        matched = _subset_sum(candidates, target_cents)
        if matched and len(matched) >= 2:
            results[i] = matched
            used.update(matched)

    return results


# ── 1-to-1 GL match ───────────────────────────────────────────────────────────

def match_transactions(
    transactions: list[ParsedTransaction],
    gl_lines: list[dict],
    skip_indices: set[int] | None = None,
) -> dict[int, int]:
    """Greedy best-match: bank txn index → GL line_id.

    Matches on amount (±$0.01) and date (±5 days).
    Each GL line is used at most once.
    """
    used: set[int] = set()
    matches: dict[int, int] = {}

    for i, txn in enumerate(transactions):
        if skip_indices and i in skip_indices:
            continue
        candidates: list[tuple[int, int]] = []  # (days_diff, line_id)
        for line in gl_lines:
            net = Decimal(str(line["debit_amount"])) - Decimal(str(line["credit_amount"]))
            if abs(net - txn.amount) >= Decimal("0.01"):
                continue
            entry_date = datetime.strptime(line["entry_date"], "%Y-%m-%d").date()
            days_diff = abs((entry_date - txn.transaction_date).days)
            if days_diff <= 5:
                candidates.append((days_diff, line["line_id"]))

        candidates.sort()
        for _, line_id in candidates:
            if line_id not in used:
                matches[i] = line_id
                used.add(line_id)
                break

    return matches


# ── File round-tripping through hidden form fields ────────────────────────────

def encode_file(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


def decode_file(b64: str) -> bytes:
    return base64.b64decode(b64)
