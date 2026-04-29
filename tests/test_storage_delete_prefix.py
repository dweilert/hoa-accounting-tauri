"""Storage backend: delete_prefix sweeps prior reports.

Verifies the LocalFileBackend's prefix-delete semantics — used by the
batch PDF service to ensure only the latest owner ledger lives in
storage, never a year-stale or name-stale leftover.

S3StorageBackend is not exercised here (would require boto3 mocking);
the contract is validated end-to-end via the local implementation.
"""

from __future__ import annotations

from pathlib import Path

from hoa_accounting.storage.backend import LocalFileBackend


def test_upload_writes_at_full_key_path(tmp_path: Path) -> None:
    backend = LocalFileBackend(tmp_path)
    backend.upload("owner-reports/L-1/2026_L-1_Alice.pdf", b"%PDF-1")
    assert (tmp_path / "owner-reports/L-1/2026_L-1_Alice.pdf").exists()


def test_delete_prefix_clears_lot_directory(tmp_path: Path) -> None:
    backend = LocalFileBackend(tmp_path)
    backend.upload("owner-reports/L-1/2025_L-1_Alice.pdf", b"%PDF-old")
    backend.upload("owner-reports/L-1/2026_L-1_Alice.pdf", b"%PDF-new")
    backend.upload("owner-reports/L-2/2026_L-2_Bob.pdf", b"%PDF-bob")

    deleted = backend.delete_prefix("owner-reports/L-1/")

    assert deleted == 2
    assert not (tmp_path / "owner-reports/L-1/2025_L-1_Alice.pdf").exists()
    assert not (tmp_path / "owner-reports/L-1/2026_L-1_Alice.pdf").exists()
    # Other lots untouched.
    assert (tmp_path / "owner-reports/L-2/2026_L-2_Bob.pdf").exists()


def test_delete_prefix_missing_path_is_no_op(tmp_path: Path) -> None:
    backend = LocalFileBackend(tmp_path)
    assert backend.delete_prefix("owner-reports/never-existed/") == 0


def test_delete_prefix_partial_match_without_trailing_slash(tmp_path: Path) -> None:
    """Prefix without trailing slash matches any key starting with it."""
    backend = LocalFileBackend(tmp_path)
    backend.upload("owner-reports/L-1/2026_L-1_Alice.pdf", b"%PDF-1")
    backend.upload("owner-reports/L-10/2026_L-10_Bob.pdf", b"%PDF-2")

    # 'owner-reports/L-1' matches both L-1/ and L-10/ — that's S3 semantics.
    deleted = backend.delete_prefix("owner-reports/L-1")
    assert deleted == 2


def test_batch_pdf_calls_delete_prefix_before_upload(tmp_path: Path) -> None:
    """Service must clear the lot's prior PDFs before writing the new one.

    Simulated with an in-memory backend that records the order of calls.
    """
    from hoa_accounting.reporting.batch_pdf import BatchPdfService

    calls: list[tuple[str, str]] = []

    class RecordingBackend:
        def upload(self, key: str, pdf_bytes: bytes, **_: object) -> str:
            calls.append(("upload", key))
            return f"file://{key}"

        def delete_prefix(self, prefix: str) -> int:
            calls.append(("delete_prefix", prefix))
            return 0

    # Minimal stub: BatchPdfService only reads `lots` table and uses the
    # service to generate; for this test we patch the service to no-op.
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE lots (id INTEGER PRIMARY KEY, lot_number TEXT, active_flag INT)"
    )
    conn.execute("INSERT INTO lots VALUES (1, 'L-1', 1)")

    svc = BatchPdfService(conn, RecordingBackend())  # type: ignore[arg-type]

    # Replace the report service with a tiny stub returning the bare
    # minimum the rest of run() needs.
    from dataclasses import dataclass

    @dataclass
    class _StubOwner:
        first_name: str = "Alice"
        last_name: str = "Park"
        display_name: str = "Alice Park"
        email: str = ""
        phone: str = ""

    @dataclass
    class _StubReport:
        lot_id: int = 1
        lot_number: str = "L-1"
        lot_address: str = "123 Test"
        year: int = 2026
        opening_balance: str = "0.00"
        closing_balance: str = "0.00"
        opening_balance_lines: list = None  # type: ignore[assignment]
        rows: list = None  # type: ignore[assignment]
        owners: list = None  # type: ignore[assignment]

        def __post_init__(self):
            self.opening_balance_lines = []
            self.rows = []
            self.owners = [_StubOwner()]

    import hoa_accounting.reporting.batch_pdf as bp

    class _StubSvc:
        def __init__(self, *_a, **_kw):
            pass

        def generate(self, *, lot_id: int, year: int):
            return _StubReport(lot_id=lot_id, year=year)

    monkey = bp.LotStatementReportService
    bp.LotStatementReportService = _StubSvc  # type: ignore[assignment]
    try:
        results = svc.run(year=2026)
    finally:
        bp.LotStatementReportService = monkey

    assert len(results) == 1 and results[0].ok
    # delete_prefix must come BEFORE upload for that lot.
    op_names = [c[0] for c in calls]
    assert op_names == ["delete_prefix", "upload"]
    assert calls[0][1] == "owner-reports/L-1/"
    assert calls[1][1].startswith("owner-reports/L-1/")
