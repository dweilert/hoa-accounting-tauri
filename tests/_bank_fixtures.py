"""Hand-rolled OFX/CSV fixture content for bank-import tests.

The bank import flow has been the longest-uncovered area in the
test suite because it lives at a file-content trust boundary —
without realistic bytes, we can't exercise the parser, the dispatch
layer, or the standalone-batch storage path.

These fixtures are intentionally minimal: just enough to drive the
parser past its happy-path branches and exercise downstream code.
Real-world bank exports are larger and more varied; treat this as
a *parser smoke test*, not a comprehensive corpus.
"""

from __future__ import annotations


# ── OFX 1.x (SGML, no closing tags on field elements) ─────────────────
# Two transactions: one deposit, one withdrawal. Single account.
SAMPLE_OFX_BYTES: bytes = (
    b"OFXHEADER:100\r\n"
    b"DATA:OFXSGML\r\n"
    b"VERSION:102\r\n"
    b"\r\n"
    b"<OFX>\r\n"
    b"<BANKMSGSRSV1>\r\n"
    b"<STMTTRNRS>\r\n"
    b"<STMTRS>\r\n"
    b"<BANKACCTFROM>\r\n"
    b"<BANKID>123456789\r\n"
    b"<ACCTID>HP-TEST-0001\r\n"
    b"<ACCTTYPE>CHECKING\r\n"
    b"</BANKACCTFROM>\r\n"
    b"<BANKTRANLIST>\r\n"
    b"<STMTTRN>\r\n"
    b"<TRNTYPE>CREDIT\r\n"
    b"<DTPOSTED>20260115120000\r\n"
    b"<TRNAMT>250.00\r\n"
    b"<FITID>HPFIT-1\r\n"
    b"<NAME>HP DEPOSIT TEST\r\n"
    b"<MEMO>fixture deposit\r\n"
    b"</STMTTRN>\r\n"
    b"<STMTTRN>\r\n"
    b"<TRNTYPE>DEBIT\r\n"
    b"<DTPOSTED>20260116120000\r\n"
    b"<TRNAMT>-42.50\r\n"
    b"<FITID>HPFIT-2\r\n"
    b"<NAME>HP WITHDRAWAL TEST\r\n"
    b"<MEMO>fixture withdrawal\r\n"
    b"</STMTTRN>\r\n"
    b"</BANKTRANLIST>\r\n"
    b"</STMTRS>\r\n"
    b"</STMTTRNRS>\r\n"
    b"</BANKMSGSRSV1>\r\n"
    b"</OFX>\r\n"
)


# ── OFX 2.x (XML form, multi-account) ─────────────────────────────────
SAMPLE_OFX_MULTIACCOUNT_BYTES: bytes = (
    b"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\r\n"
    b"<?OFX OFXHEADER=\"200\" VERSION=\"211\"?>\r\n"
    b"<OFX>\r\n"
    b" <BANKMSGSRSV1>\r\n"
    b"  <STMTTRNRS>\r\n"
    b"   <STMTRS>\r\n"
    b"    <BANKACCTFROM><ACCTID>HP-MULTI-A</ACCTID></BANKACCTFROM>\r\n"
    b"    <BANKTRANLIST>\r\n"
    b"     <STMTTRN><TRNTYPE>CREDIT</TRNTYPE><DTPOSTED>20260201</DTPOSTED>"
    b"<TRNAMT>100.00</TRNAMT><FITID>M-A-1</FITID>"
    b"<NAME>multi A credit</NAME></STMTTRN>\r\n"
    b"    </BANKTRANLIST>\r\n"
    b"   </STMTRS>\r\n"
    b"   <STMTRS>\r\n"
    b"    <BANKACCTFROM><ACCTID>HP-MULTI-B</ACCTID></BANKACCTFROM>\r\n"
    b"    <BANKTRANLIST>\r\n"
    b"     <STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260201</DTPOSTED>"
    b"<TRNAMT>-50.00</TRNAMT><FITID>M-B-1</FITID>"
    b"<NAME>multi B debit</NAME></STMTTRN>\r\n"
    b"    </BANKTRANLIST>\r\n"
    b"   </STMTRS>\r\n"
    b"  </STMTTRNRS>\r\n"
    b" </BANKMSGSRSV1>\r\n"
    b"</OFX>\r\n"
)


# ── CSV (signed-amount column) ────────────────────────────────────────
SAMPLE_CSV_SIGNED_BYTES: bytes = (
    b"Date,Amount,Description\r\n"
    b"2026-01-15,250.00,HP CSV deposit\r\n"
    b"2026-01-16,-42.50,HP CSV withdrawal\r\n"
    b"2026-01-17,1000.00,HP CSV payroll\r\n"
)


# ── CSV (split debit/credit columns) ──────────────────────────────────
SAMPLE_CSV_DEBIT_CREDIT_BYTES: bytes = (
    b"Posted Date,Description,Debit,Credit\r\n"
    b"2026-02-01,HP CSV utility bill,75.00,\r\n"
    b"2026-02-02,HP CSV interest,,12.34\r\n"
)


# ── Malformed (header-only OFX, no transactions) ──────────────────────
# Useful for verifying empty-file handling.
EMPTY_OFX_BYTES: bytes = (
    b"OFXHEADER:100\r\nDATA:OFXSGML\r\n"
    b"<OFX></OFX>\r\n"
)
