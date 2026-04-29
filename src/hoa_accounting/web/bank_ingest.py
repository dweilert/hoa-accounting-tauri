"""Bank file ingest: canonical record + adapter layer.

Everything upstream of this module deals with bank quirks (OFX dialects,
CSV column orderings, manual data entry). Everything downstream
(``bank_transactions``, rule engine, Pending Validation, reconciliation)
deals with ``CanonicalBankTxn`` only.

Adding a new bank format = writing a new ``BankFileAdapter`` and calling
``register_adapter``. Nothing else changes.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from hoa_accounting.web.bank_statement_import import (
    ParsedTransaction,
    ParseError,
    detect_format,
    parse_csv,
    parse_ofx,
    parse_ofx_by_account,
)

# ── Canonical transaction type vocabulary ──────────────────────────────────

# Every adapter emits one of these. Everything downstream pattern-matches
# against this short list; bank-specific values (OFX TRNTYPE = 'SRVCHG',
# CSV 'Point of Sale', etc.) are squashed at the adapter boundary.
CANONICAL_TRN_TYPES = {
    "DEBIT",  # generic debit / withdrawal
    "CREDIT",  # generic credit / deposit
    "FEE",  # bank fee, service charge, NSF
    "CHECK",  # check paid (has check_number)
    "ACH",  # ACH / electronic transfer either direction
    "TRANSFER",  # intra-bank transfer between accounts
    "INTEREST",  # interest credited or debited
    "OTHER",  # fallback when the source gives no usable hint
}

# OFX TRNTYPE → canonical mapping. Missing entries fall through to OTHER.
_OFX_TRNTYPE_MAP: dict[str, str] = {
    "CREDIT": "CREDIT",
    "DEBIT": "DEBIT",
    "DEP": "CREDIT",
    "DIRECTDEP": "ACH",
    "DIRECTDEBIT": "ACH",
    "REPEATPMT": "ACH",
    "PAYMENT": "ACH",
    "XFER": "TRANSFER",
    "CHECK": "CHECK",
    "FEE": "FEE",
    "SRVCHG": "FEE",
    "INT": "INTEREST",
    "DIV": "INTEREST",
    "ATM": "DEBIT",
    "POS": "DEBIT",
    "CASH": "DEBIT",
    "OTHER": "OTHER",
}


def normalize_trn_type(raw: str) -> str:
    """Return a value from ``CANONICAL_TRN_TYPES`` for any adapter input.

    Adapters call this rather than inventing mappings — keeps the canonical
    set authoritative and the adapters thin.
    """
    if not raw:
        return "OTHER"
    upper = raw.strip().upper()
    if upper in CANONICAL_TRN_TYPES:
        return upper
    return _OFX_TRNTYPE_MAP.get(upper, "OTHER")


# ── Canonical record ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CanonicalBankTxn:
    """One bank line in the format the rest of the system speaks.

    Fields are all post-normalization — no adapter-specific quirks leak
    past this boundary. The adapter's job is to produce these.
    """

    posted_at: date
    amount: Decimal  # signed: + = deposit, − = debit
    description: str
    memo: str
    transaction_type: str  # ∈ CANONICAL_TRN_TYPES
    check_number: str = ""  # when a check or ref number is visible
    external_ref: str = ""  # FITID or bank-assigned id, audit only
    raw: dict[str, Any] = field(
        default_factory=dict[str, Any], compare=False, hash=False
    )

    # Compatibility accessors — the rule matcher and legacy paths still
    # refer to a few ``ParsedTransaction``-era field names. Keep them
    # working without a rename sweep.
    @property
    def transaction_date(self) -> date:  # noqa: D401 - compat
        return self.posted_at

    @property
    def fitid(self) -> str:  # noqa: D401 - compat
        return self.external_ref

    def content_fingerprint(self, bank_account_id: int) -> str:
        """SHA-256 of the fields that identify this line per bank account.

        Crucially excludes ``external_ref`` — identity is derived from the
        posted event, not from the bank's (sometimes flaky) FITID. That
        way:

        - If the bank reissues a statement with different FITIDs for the
          same real transactions, we still dedupe correctly.
        - If the bank reuses a FITID across different real transactions,
          content differs and we record both (as we should).

        ``check_number`` is included to break ties when a bank reports two
        genuinely distinct same-day same-amount same-description lines
        (the classic example: two identical ATM fees). Residual collisions
        with no distinguishing field are accepted as a rare, low-impact
        cost — callers can surface them at reconciliation if they matter.
        """
        blob = "|".join(
            [
                str(bank_account_id),
                self.posted_at.isoformat(),
                str(self.amount),
                self.description or "",
                self.memo or "",
                self.transaction_type or "",
                self.check_number or "",
            ]
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def dedup_key(self, bank_account_id: int) -> str:
        """Per-account unique identifier used by ``bank_transactions``."""
        return "h:" + self.content_fingerprint(bank_account_id)


# ── Adapter protocol + registry ─────────────────────────────────────────────


class BankFileAdapter(Protocol):
    """Every ingest source (OFX, CSV-flavor-X, manual, …) implements this."""

    name: str

    def detect(self, content: bytes) -> float:
        """Confidence 0.0–1.0 that this adapter can parse ``content``.

        The dispatcher picks the highest-scoring adapter. Scores below
        ``DETECT_THRESHOLD`` indicate "looks plausible but needs a saved
        column map before parse" — the caller routes to the mapping
        wizard in that case.
        """
        ...

    def parse(
        self,
        content: bytes,
        mapping: dict[str, Any] | None = None,
    ) -> list[CanonicalBankTxn]:
        """Parse to canonical records. ``mapping`` is the saved column
        map for CSV-style adapters; OFX and manual adapters ignore it."""
        ...


DETECT_THRESHOLD = 0.8  # below this, require a mapping before parse

_registry: list[BankFileAdapter] = []


def register_adapter(adapter: BankFileAdapter) -> None:
    """Register an adapter. Called once at module import for built-ins."""
    _registry.append(adapter)


def list_adapters() -> list[BankFileAdapter]:
    return list(_registry)


@dataclass(frozen=True)
class DispatchResult:
    adapter: BankFileAdapter
    score: float
    needs_mapping: bool


def dispatch(content: bytes) -> DispatchResult:
    """Pick the best adapter for ``content``.

    Returns the top scorer regardless of confidence — the caller inspects
    ``needs_mapping`` to decide whether to route the user to the mapping
    wizard first. Raises ``ParseError`` if no adapter scores above zero.
    """
    if not _registry:
        raise ParseError("No bank file adapters registered.")
    ranked = sorted(
        ((a.detect(content), a) for a in _registry),
        key=lambda t: t[0],
        reverse=True,
    )
    top_score, top = ranked[0]
    if top_score <= 0.0:
        raise ParseError(
            "Unrecognized file format. Supported: OFX/QFX, CSV. "
            "If this is a CSV from a new bank, upload it again and the "
            "mapping wizard will walk you through identifying the columns."
        )
    return DispatchResult(
        adapter=top,
        score=top_score,
        needs_mapping=top_score < DETECT_THRESHOLD,
    )


# ── Built-in adapters (wrappers over existing parsers) ─────────────────────


def canonical_from_parsed(
    p: ParsedTransaction,
    source_raw_type: str,
) -> CanonicalBankTxn:
    """Lift a legacy ``ParsedTransaction`` to canonical form.

    Shared by the OFX and built-in CSV adapters so the normalization
    rules live in one place.
    """
    return CanonicalBankTxn(
        posted_at=p.transaction_date,
        amount=p.amount,
        description=p.description or "",
        memo=p.memo or "",
        transaction_type=normalize_trn_type(source_raw_type or p.transaction_type),
        check_number="",  # legacy parsers don't extract it separately
        external_ref=p.fitid or "",
        raw={"source_type": p.transaction_type, "fitid": p.fitid},
    )


class OFXAdapter:
    """OFX / QFX / QBO — structured format, no mapping ever required."""

    name = "ofx"

    def detect(self, content: bytes) -> float:
        try:
            sample = content[:600].decode("utf-8", errors="replace").upper()
        except Exception:
            return 0.0
        if "OFXHEADER" in sample or "<OFX>" in sample or "OFXSGML" in sample:
            return 1.0
        return 0.0

    def parse(
        self,
        content: bytes,
        mapping: dict[str, Any] | None = None,
    ) -> list[CanonicalBankTxn]:
        parsed = parse_ofx(content)
        return [canonical_from_parsed(p, p.transaction_type) for p in parsed]


class CSVAdapter:
    """Generic CSV — detects shape, requires a column mapping to parse.

    ``detect`` returns a modest (sub-threshold) score so the dispatcher
    routes the user to the mapping wizard on first upload from a new
    bank. Once a mapping is saved and passed in, ``parse`` runs silently.
    """

    name = "csv"

    def detect(self, content: bytes) -> float:
        try:
            text = content[:1200].decode("utf-8", errors="replace")
        except Exception:
            return 0.0
        first = next((ln for ln in text.splitlines() if ln.strip()), "")
        if "," in first and len(first) < 4096:
            # Plausible CSV. Keep below threshold so the caller is forced
            # to confirm / map columns before we commit to a parse.
            return 0.6
        return 0.0

    # Canonical field → legacy ``parse_csv`` column_map key. The wizard
    # hands us canonical keys; parse_csv still speaks its own vocabulary.
    _CANONICAL_TO_LEGACY = {
        "transaction_date": "date",
        "amount": "amount",
        "amount_debit": "debit",
        "amount_credit": "credit",
        "description": "description",
    }

    def parse(
        self,
        content: bytes,
        mapping: dict[str, Any] | None = None,
    ) -> list[CanonicalBankTxn]:
        legacy_map: dict[str, str] | None = None
        if mapping:
            legacy_map = {}
            for canonical_key, csv_col in mapping.items():
                if not csv_col:
                    continue
                legacy_key = self._CANONICAL_TO_LEGACY.get(canonical_key)
                if legacy_key:
                    legacy_map[legacy_key] = csv_col
        parsed, _headers, _resolved = parse_csv(content, legacy_map)
        return [canonical_from_parsed(p, p.transaction_type) for p in parsed]


# Register built-ins at module import.
register_adapter(OFXAdapter())
register_adapter(CSVAdapter())


# ── CSV header fingerprinting + saved mappings ──────────────────────────────

# Canonical fields the bank-CSV mapping produces. These are what the CSV
# adapter reads via ``mapping[canonical_field] = csv_header``. Kept here
# so the mapping wizard and the ingest adapter agree on the vocabulary.
CANONICAL_CSV_FIELDS: list[dict[str, Any]] = [
    {
        "name": "transaction_date",
        "label": "Date",
        "required": True,
        "note": "YYYY-MM-DD, MM/DD/YYYY, or similar",
    },
    {
        "name": "amount",
        "label": "Amount",
        "required": True,
        "note": "Signed: negative = debit. Use 'amount_debit'/'amount_credit' "
        "if the bank splits them into separate columns.",
    },
    {
        "name": "amount_debit",
        "label": "Debit Amount",
        "required": False,
        "note": "Optional. Use only when the bank splits debit/credit columns.",
    },
    {
        "name": "amount_credit",
        "label": "Credit Amount",
        "required": False,
        "note": "Optional. Use only when the bank splits debit/credit columns.",
    },
    {"name": "description", "label": "Description", "required": True},
    {"name": "memo", "label": "Memo", "required": False},
    {
        "name": "transaction_type",
        "label": "Type",
        "required": False,
        "note": "Will be normalized to DEBIT/CREDIT/FEE/CHECK/ACH/…",
    },
    {
        "name": "check_number",
        "label": "Check Number",
        "required": False,
        "note": "Optional. Helps disambiguate same-day same-amount lines.",
    },
    {
        "name": "external_ref",
        "label": "Reference",
        "required": False,
        "note": "Optional. Bank-provided transaction id; audit-only.",
    },
]


def read_csv_headers(content: bytes) -> list[str]:
    """Return the first non-empty row of a CSV file as a list of headers."""
    import csv as _csv
    import io as _io

    text = content.decode("utf-8-sig", errors="replace")
    for row in _csv.reader(_io.StringIO(text)):
        if any(cell.strip() for cell in row):
            return [cell.strip() for cell in row]
    return []


def fingerprint_csv_headers(content: bytes) -> str:
    """Stable identifier for a CSV "shape" — the hash of its header row.

    Used to key saved mappings per bank account. Two uploads from the
    same bank produce the same fingerprint even if transaction rows
    differ; a bank that changes its column layout gets a new fingerprint
    and re-prompts the mapping wizard.
    """
    headers = read_csv_headers(content)
    normalized = "|".join(h.strip().lower() for h in headers)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def lookup_csv_mapping(
    conn: sqlite3.Connection,
    bank_account_id: int,
    fingerprint: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT mapping_json FROM bank_account_file_formats "
        "WHERE bank_account_id = ? AND fingerprint = ?",
        (bank_account_id, fingerprint),
    ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row[0])  # type: ignore[no-any-return]
    except (TypeError, ValueError):
        return None


def save_csv_mapping(
    conn: sqlite3.Connection,
    bank_account_id: int,
    fingerprint: str,
    mapping: dict[str, Any],
    sample_headers: list[str],
) -> None:
    conn.execute(
        """
        INSERT INTO bank_account_file_formats
            (bank_account_id, fingerprint, mapping_json, sample_headers_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (bank_account_id, fingerprint)
        DO UPDATE SET mapping_json = excluded.mapping_json,
                      sample_headers_json = excluded.sample_headers_json
        """,
        (bank_account_id, fingerprint, json.dumps(mapping), json.dumps(sample_headers)),
    )
    conn.commit()


# ── Stash: short-lived holding area for uploaded files ─────────────────────


def stash_upload(
    conn: sqlite3.Connection,
    bank_account_id: int,
    filename: str,
    content: bytes,
) -> str:
    """Save ``content`` for retrieval after the mapping wizard runs.

    The token lives on the URL so a page reload doesn't lose the upload.
    Consumed by ``consume_stash`` once ingest succeeds.
    """
    token = secrets.token_urlsafe(16)
    conn.execute(
        """
        INSERT INTO bank_import_stash
            (token, bank_account_id, filename, file_content)
        VALUES (?, ?, ?, ?)
        """,
        (token, bank_account_id, filename, content),
    )
    conn.commit()
    return token


def peek_stash(
    conn: sqlite3.Connection,
    token: str,
) -> tuple[int, str, bytes] | None:
    """Return ``(bank_account_id, filename, file_content)`` without deleting.
    Used by the wizard page to fetch the CSV for preview/mapping."""
    row = conn.execute(
        "SELECT bank_account_id, filename, file_content FROM bank_import_stash WHERE token = ?",
        (token,),
    ).fetchone()
    if row is None:
        return None
    return int(row[0]), str(row[1] or ""), bytes(row[2])


def consume_stash(
    conn: sqlite3.Connection,
    token: str,
) -> tuple[int, str, bytes] | None:
    """Fetch and remove a stash entry. Returns None if the token is invalid
    or already consumed."""
    row = peek_stash(conn, token)
    if row is None:
        return None
    conn.execute("DELETE FROM bank_import_stash WHERE token = ?", (token,))
    conn.commit()
    return row


# ── Convenience re-exports ──────────────────────────────────────────────────

__all__ = [
    "CANONICAL_TRN_TYPES",
    "CANONICAL_CSV_FIELDS",
    "CanonicalBankTxn",
    "BankFileAdapter",
    "DispatchResult",
    "DETECT_THRESHOLD",
    "OFXAdapter",
    "CSVAdapter",
    "canonical_from_parsed",
    "dispatch",
    "normalize_trn_type",
    "register_adapter",
    "list_adapters",
    # CSV mapping persistence
    "read_csv_headers",
    "fingerprint_csv_headers",
    "lookup_csv_mapping",
    "save_csv_mapping",
    # Stash between upload and mapping
    "stash_upload",
    "peek_stash",
    "consume_stash",
    # Legacy helpers still useful to callers during cutover
    "ParseError",
    "detect_format",
    "parse_ofx_by_account",
]
