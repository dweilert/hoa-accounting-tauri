"""OFX Inbox page + webhook + fetcher proxy.

The separate fetcher daemon (repo: dweilert/hoa_downloader) drops OFX
files into a shared inbox folder and pings this app at /api/ofx-ready
when done. Users can also kick off an on-demand fetch from this page,
which proxies server-side to the daemon on 127.0.0.1:17866.

Key decisions baked in:
- /api/ofx-ready is CSRF + auth exempt (no session on the fetcher side)
  and path-validates its payload against the configured inbox root.
- On success the import is dispatched to a background thread so the
  webhook returns 200 immediately (fetcher doesn't read the body).
- Files move to inbox/archive/<YYYY>/<MM>/ after successful import;
  nothing is ever deleted.
- Fetch buttons proxy through this app rather than hitting the daemon
  from the browser so CSRF + existing auth layer still apply.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import URLError

from hoa_accounting.web.bank_statement_pages import BankStatementPages
from hoa_accounting.web.template_engine import render_template


_log = logging.getLogger(__name__)

# Daemon lives on localhost only; both proxy calls short-time out.
_FETCHER_BASE_URL = "http://127.0.0.1:17866"
_FETCHER_ENQUEUE_TIMEOUT = 5.0   # seconds — /fetch returns 202 fast
_FETCHER_STATUS_TIMEOUT  = 2.0   # seconds — /status is a quick read

# Consider the daemon dead when heartbeat.txt is older than this.
_HEARTBEAT_STALE_SECONDS = 180

# File names the fetcher writes at the inbox root.
_HEARTBEAT_FILE   = "heartbeat.txt"
_LAST_SUCCESS    = "last_success.txt"
_LAST_FAILURE    = "last_failure.txt"


@dataclass(frozen=True)
class OFXInboxResponse:
    status_code: int
    body_html: str


def _inbox_root(org: dict | None) -> Path:
    """Return the inbox directory, creating it on first access.

    Pulled from config (``ofx_inbox_path``) with a sensible default so
    a fresh install doesn't need a config edit before the page loads.
    """
    raw = (org or {}).get("ofx_inbox_path") or "~/hoa-system/ofx-inbox"
    root = Path(str(raw)).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _parse_status_file(p: Path) -> dict | None:
    """Parse a loose key: value status file (timestamp + fields).

    Format is the fetcher's — grep-friendly, not strict. We accept any
    ``key: value`` line, skip blanks, tolerate occasional garbage.
    Returns None when the file doesn't exist.
    """
    if not p.exists():
        return None
    out: dict[str, str] = {}
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            out[k.strip().lower()] = v.strip()
    except OSError:
        return None
    return out or None


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        # The fetcher writes ISO-8601 with offset. fromisoformat handles it
        # from Python 3.11+; our runtime is 3.14.
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _list_inbox_files(root: Path) -> list[dict]:
    """OFX files awaiting import (sitting at the inbox root, not archive).

    Returns each as a dict with filename, mtime (iso), and size (bytes).
    """
    items = []
    for entry in sorted(root.glob("*.ofx")):
        try:
            st = entry.stat()
        except OSError:
            continue
        items.append({
            "filename": entry.name,
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "size": st.st_size,
        })
    return items


def _archive_filenames(root: Path) -> set[str]:
    """Every OFX filename already in archive/. Used to distinguish
    'fetched but not imported' from 'fetched and imported' on the
    banner, as agreed."""
    archive = root / "archive"
    if not archive.exists():
        return set()
    return {p.name for p in archive.rglob("*.ofx")}


def _safe_inbox_path(root: Path, claimed_path: str) -> Path | None:
    """Resolve ``claimed_path`` and confirm it sits inside ``root``.

    Rejects traversal / absolute paths pointing outside the inbox. Used
    by the webhook before opening a file it was handed by the fetcher.
    """
    try:
        candidate = Path(claimed_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


class OFXInboxPages:
    """Render the inbox page + back-end endpoints."""

    TEMPLATE = "ofx_inbox.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── Inbox page ──────────────────────────────────────────────────

    def render_inbox(
        self,
        *,
        org: dict | None,
        theme: str,
        flash_message: str = "",
        error_message: str = "",
    ) -> OFXInboxResponse:
        root = _inbox_root(org)
        files = _list_inbox_files(root)
        archived = _archive_filenames(root)
        heartbeat = _parse_status_file(root / _HEARTBEAT_FILE)
        success   = _parse_status_file(root / _LAST_SUCCESS)
        failure   = _parse_status_file(root / _LAST_FAILURE)

        # Banner precedence: heartbeat red/neutral → last_failure yellow →
        # last_success green.
        banner = self._build_banner(heartbeat, success, failure, archived)

        ctx = {
            "heading": "OFX Inbox",
            "org": org or {},
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "ofx-inbox",
            "breadcrumb": "Money In · Receiving",
            "parent_url": "/",
            "files": files,
            "inbox_root": str(root),
            "banner": banner,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return OFXInboxResponse(
            status_code=status,
            body_html=render_template(self.TEMPLATE, ctx),
        )

    def _build_banner(
        self,
        heartbeat: dict | None,
        success: dict | None,
        failure: dict | None,
        archived: set[str],
    ) -> dict:
        now = datetime.now(tz=timezone.utc)

        # Heartbeat check — missing on fresh install (neutral), stale = red.
        if heartbeat is None:
            if success is None and failure is None:
                return {
                    "level": "neutral",
                    "title": "Fetcher not yet run",
                    "detail": "Press Fetch now to pull bank data for the first time.",
                }
        else:
            hb_ts = _parse_ts(heartbeat.get("timestamp"))
            if hb_ts is not None:
                age = (now - hb_ts.astimezone(timezone.utc)).total_seconds()
                if age > _HEARTBEAT_STALE_SECONDS:
                    mins = int(age // 60)
                    return {
                        "level": "danger",
                        "title": "OFX fetcher is down",
                        "detail": f"No heartbeat for {mins} minute(s). Check the fetcher daemon.",
                    }

        # last_failure newer than last_success → yellow
        fail_ts = _parse_ts((failure or {}).get("timestamp"))
        succ_ts = _parse_ts((success or {}).get("timestamp"))

        if fail_ts is not None and (succ_ts is None or fail_ts > succ_ts):
            return {
                "level": "warning",
                "title": f"OFX pull failed: {(failure or {}).get('error', 'unknown error')}",
                "detail": (failure or {}).get("message", ""),
                "debug_bundle": (failure or {}).get("debug_bundle", ""),
            }

        # Success path. Annotate with "imported" vs "awaiting import" by
        # cross-referencing the files listed in last_success against the
        # archive directory.
        if succ_ts is not None:
            listed = [
                name.strip()
                for name in ((success or {}).get("files", "") or "").split(",")
                if name.strip()
            ]
            done = sum(1 for n in listed if n in archived)
            pending = len(listed) - done
            when = succ_ts.astimezone().strftime("%a %H:%M %b %d")
            if listed:
                if pending == 0:
                    detail = f"{len(listed)} file(s) fetched, all imported ✓"
                elif done == 0:
                    detail = f"{len(listed)} file(s) fetched, awaiting import"
                else:
                    detail = (
                        f"{len(listed)} file(s) fetched; {done} imported ✓, "
                        f"{pending} awaiting import"
                    )
            else:
                detail = "fetch completed"
            return {
                "level": "ok",
                "title": f"Last pull: {when}",
                "detail": detail,
            }

        # No signal at all — shouldn't happen after the heartbeat check,
        # but fall through neutrally.
        return {
            "level": "neutral",
            "title": "No fetch activity yet",
            "detail": "",
        }

    # ── Webhook ─────────────────────────────────────────────────────

    def handle_ofx_ready(self, *, payload: dict, org: dict | None) -> tuple[int, str]:
        """Process a webhook POST from the fetcher.

        Returns (http_status, body) for the caller to turn into a Flask
        response. Always returns 200 so the fetcher doesn't retry; any
        per-payload problem is logged instead.
        """
        if not isinstance(payload, dict):
            _log.warning("ofx_ready: payload was not a JSON object")
            return 200, ""

        status = str(payload.get("status") or "").lower()
        job_id = str(payload.get("job_id") or "?")

        if status == "failure":
            _log.warning(
                "ofx_ready: fetcher reported failure — job=%s error=%s message=%s",
                job_id,
                payload.get("error"),
                payload.get("message"),
            )
            return 200, ""

        if status != "success":
            _log.warning("ofx_ready: unknown status value %r (job %s)", status, job_id)
            return 200, ""

        claimed_path = str(payload.get("path") or "")
        if not claimed_path:
            _log.warning("ofx_ready: success payload had no path (job %s)", job_id)
            return 200, ""

        root = _inbox_root(org)
        safe = _safe_inbox_path(root, claimed_path)
        if safe is None:
            _log.warning(
                "ofx_ready: rejected path %r — not inside inbox %s (job %s)",
                claimed_path, root, job_id,
            )
            return 200, ""

        # Fire-and-forget. The fetcher doesn't read our response and we
        # don't want to block it on a multi-megabyte OFX import.
        threading.Thread(
            target=self._import_and_archive,
            args=(safe, root, str(org and org.get("db_path")) or ""),
            daemon=True,
            name=f"ofx-import-{safe.name}",
        ).start()
        return 200, ""

    def _import_and_archive(self, ofx_path: Path, root: Path, db_path: str) -> None:
        """Background worker: import one OFX and archive on success."""
        try:
            from hoa_accounting.db.connection import connect_sqlite
            # Background thread owns its own connection — sqlite3 objects
            # aren't shareable across threads.
            conn = connect_sqlite(db_path) if db_path else self.conn
            try:
                result = self._import_one(conn, ofx_path)
            finally:
                if db_path and conn is not self.conn:
                    conn.close()

            if result["ok"]:
                _move_to_archive(ofx_path, root)
                _log.info(
                    "ofx-import: %s → archived (%d batches, %d transactions)",
                    ofx_path.name, result["batches"], result["transactions"],
                )
            else:
                _log.warning(
                    "ofx-import: %s left in inbox — %s",
                    ofx_path.name, result["error"],
                )
        except Exception:
            _log.exception("ofx-import: unhandled error on %s", ofx_path.name)

    def _import_one(self, conn: sqlite3.Connection, ofx_path: Path) -> dict:
        """Read + route an OFX through the existing agnostic upload path.

        handle_agnostic_upload splits by ACCTID and maps each section to
        the matching bank_accounts row by account_last4. Rule engine
        fires during apply to auto-post single-entry records.

        Returns a result dict: {ok, batches, transactions, error?}.
        """
        from flask import g

        try:
            file_bytes = ofx_path.read_bytes()
        except OSError as exc:
            return {"ok": False, "batches": 0, "transactions": 0,
                    "error": f"read failed: {exc}"}

        pages = BankStatementPages(conn)
        org = getattr(g, "org", {}) or {}
        # handle_agnostic_upload needs org + theme; theme isn't used in
        # the import math, just in rendered responses we discard here.
        redirect_url, form_resp, warnings = pages.handle_agnostic_upload(
            file_bytes=file_bytes,
            filename=ofx_path.name,
            csv_bank_account_id=None,
            org=org,
            theme=str(org.get("theme", "warm")),
        )
        if form_resp is not None:
            # Agnostic upload returns a page-response on error (unknown
            # ACCTID, parse failure, etc.). Treat as a file-level failure.
            return {"ok": False, "batches": 0, "transactions": 0,
                    "error": "agnostic upload rejected the file (see fetcher page for details)"}

        # Surface skipped-account warnings prominently — without this they
        # were silently dropped and the user would never know an OFX
        # section never landed (e.g. Reserve account section in a file
        # uploaded before the Reserve bank record existed).
        for w in warnings:
            _log.warning("ofx-import %s: %s", ofx_path.name, w)

        # Count what landed to put in the log line. Cheap: look at the
        # batches for the most recent import timestamp for this filename.
        cur = conn.execute(
            """
            SELECT COUNT(*) AS b, COALESCE(SUM(transaction_count), 0) AS t
            FROM bank_import_batches
            WHERE source_filename = ?
            """,
            (ofx_path.name,),
        ).fetchone()
        return {
            "ok": True,
            "batches": int(cur["b"] or 0),
            "transactions": int(cur["t"] or 0),
        }

    # ── Manual import (from the inbox page) ────────────────────────

    def handle_import_one(
        self, *, filename: str, org: dict | None,
    ) -> tuple[str, str]:
        """Synchronous import of a single file, clicked from the page.

        Returns (redirect_url, flash_message).
        """
        root = _inbox_root(org)
        target = root / filename
        safe = _safe_inbox_path(root, str(target))
        if safe is None or not safe.is_file():
            return "/ofx-inbox", f"File not found: {filename}"

        result = self._import_one(self.conn, safe)
        if result["ok"]:
            _move_to_archive(safe, root)
            return (
                "/ofx-inbox?msg=Imported+" + filename,
                f"Imported {filename} — {result['batches']} batch(es), "
                f"{result['transactions']} transaction(s).",
            )
        return (
            "/ofx-inbox?err=" + str(result['error']).replace(' ', '+'),
            f"Import failed for {filename}: {result['error']}",
        )

    def handle_delete(
        self, *, filename: str, org: dict | None,
    ) -> tuple[str, str]:
        """Delete a pending OFX file without importing it.

        Files in the inbox root are pending — once imported they're moved
        into ``archive/`` and disappear from this listing. Deleting just
        prevents an unwanted file (test data, duplicate, etc.) from ever
        being imported. Archived files aren't reachable through this
        action.

        Returns ``(redirect_url, flash_message)``.
        """
        root = _inbox_root(org)
        target = root / filename
        safe = _safe_inbox_path(root, str(target))
        if safe is None or not safe.is_file():
            return "/ofx-inbox", f"File not found: {filename}"
        # Only allow deleting files at the inbox root (pending). Archive
        # files are off-limits — they represent imported transactions and
        # are kept as audit history.
        if safe.parent.resolve() != root.resolve():
            return "/ofx-inbox", f"Refusing to delete {filename}: outside inbox."
        try:
            safe.unlink()
        except OSError as exc:
            return ("/ofx-inbox?err=" + str(exc).replace(" ", "+"),
                    f"Could not delete {filename}: {exc}")
        return (
            "/ofx-inbox?msg=Deleted+" + filename,
            f"Deleted {filename} (was not imported).",
        )

    def handle_import_all(self, *, org: dict | None) -> tuple[str, str]:
        """Import every unprocessed file. Keep going on per-file failure
        and report counts — as agreed."""
        root = _inbox_root(org)
        files = _list_inbox_files(root)
        ok = 0
        failed: list[str] = []
        for item in files:
            path = root / item["filename"]
            result = self._import_one(self.conn, path)
            if result["ok"]:
                _move_to_archive(path, root)
                ok += 1
            else:
                failed.append(f"{item['filename']}: {result['error']}")

        if not files:
            return "/ofx-inbox", "Nothing to import."
        if not failed:
            return "/ofx-inbox?msg=Imported+" + str(ok), f"Imported {ok} file(s)."
        return (
            "/ofx-inbox?msg=Partial",
            f"Imported {ok}, failed {len(failed)}. "
            + "; ".join(failed[:3])
            + ("…" if len(failed) > 3 else ""),
        )

    # ── Fetcher proxy (server-side HTTP to 127.0.0.1:17866) ────────

    def proxy_fetch(self, *, mode: str = "headless") -> tuple[int, dict | str]:
        """POST to the fetcher daemon. ``mode`` is 'headless' or 'headed'.

        Returns (http_status, body_json_or_text). The page shows the
        ``job_id`` or surfaces a connection error if the daemon is down.
        """
        endpoint = "/fetch-headed" if mode == "headed" else "/fetch"
        return _post_to_fetcher(endpoint)

    def proxy_status(self) -> tuple[int, dict | str]:
        return _get_from_fetcher("/status", timeout=_FETCHER_STATUS_TIMEOUT)


# ── Helpers ──────────────────────────────────────────────────────────

def _move_to_archive(ofx_path: Path, root: Path) -> Path:
    """Move an imported OFX into archive/<YYYY>/<MM>/<name>.

    Never overwrites — appends _1, _2, etc. on collision.
    """
    now = datetime.now()
    dest_dir = root / "archive" / f"{now.year}" / f"{now.month:02d}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / ofx_path.name
    n = 1
    stem = ofx_path.stem
    suffix = ofx_path.suffix
    while dest.exists():
        dest = dest_dir / f"{stem}_{n}{suffix}"
        n += 1
    ofx_path.rename(dest)
    return dest


def _post_to_fetcher(endpoint: str) -> tuple[int, dict | str]:
    url = _FETCHER_BASE_URL + endpoint
    req = urlrequest.Request(
        url, data=b"", method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlrequest.urlopen(req, timeout=_FETCHER_ENQUEUE_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body) if body else {}
            except json.JSONDecodeError:
                return resp.status, body
    except URLError as exc:
        return 503, f"fetcher unreachable at {url}: {exc}"
    except Exception as exc:  # noqa: BLE001 — surface everything to the UI
        return 500, f"fetcher error: {exc}"


def _get_from_fetcher(endpoint: str, *, timeout: float) -> tuple[int, dict | str]:
    url = _FETCHER_BASE_URL + endpoint
    try:
        with urlrequest.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body) if body else {}
            except json.JSONDecodeError:
                return resp.status, body
    except URLError as exc:
        return 503, f"fetcher unreachable at {url}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return 500, f"fetcher error: {exc}"
