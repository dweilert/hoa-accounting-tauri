"""S3 cloud backup settings and push/pull page."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from hoa_accounting.bootstrap.s3_sync import (
    S3Config,
    list_backups,
    load_s3_config,
    pull_backup,
    push_backup,
    save_s3_config,
    test_connection,
)
from hoa_accounting.web.template_engine import render_template


class S3BackupPageResponse:
    def __init__(self, status_code: int, body_html: str) -> None:
        self.status_code = status_code
        self.body_html = body_html


class S3BackupPages:
    TEMPLATE = "s3_backup.html"

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _load(self) -> S3Config:
        return load_s3_config(self._db_path)

    def render_page(
        self,
        *,
        org: dict[str, Any],
        theme: str,
        flash: str = "",
        error: str = "",
        cfg: S3Config | None = None,
    ) -> S3BackupPageResponse:
        if cfg is None:
            cfg = self._load()
        backups = list_backups(cfg) if cfg.is_configured else []
        ctx = {
            "heading": "S3 Cloud Backup",
            "org": org,
            "theme": theme,
            "page_key": "s3-backup",
            "breadcrumb": "Admin",
            "flash": flash,
            "error": error,
            "cfg": cfg,
            "backups": backups,
        }
        return S3BackupPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.TEMPLATE, ctx),
        )

    def handle_save(
        self,
        *,
        org: dict[str, Any],
        theme: str,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        prefix: str,
    ) -> tuple[str | None, S3BackupPageResponse | None]:
        """Save S3 credentials. Returns (redirect_url, page_response)."""
        bucket = bucket.strip()
        region = region.strip() or "us-east-1"
        prefix = prefix.strip() or "db-backups/"
        if not bucket:
            cfg = S3Config(
                bucket=bucket,
                region=region,
                access_key_id=access_key_id.strip(),
                secret_access_key=secret_access_key.strip(),
                prefix=prefix,
            )
            return None, self.render_page(
                org=org, theme=theme, error="Bucket name is required.", cfg=cfg
            )
        cfg = S3Config(
            bucket=bucket,
            region=region,
            access_key_id=access_key_id.strip(),
            secret_access_key=secret_access_key.strip(),
            prefix=prefix,
        )
        save_s3_config(self._db_path, cfg)
        from urllib.parse import quote

        return f"/admin/s3-backup?msg={quote('S3 settings saved.')}", None

    def handle_test(
        self,
        *,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        prefix: str,
    ) -> dict[str, Any]:
        """Test connection — returns JSON-serialisable dict."""
        cfg = S3Config(
            bucket=bucket.strip(),
            region=region.strip() or "us-east-1",
            access_key_id=access_key_id.strip(),
            secret_access_key=secret_access_key.strip(),
            prefix=prefix.strip() or "db-backups/",
        )
        ok, msg = test_connection(cfg)
        return {"ok": ok, "message": msg}

    def handle_push(
        self, *, org: dict[str, Any], theme: str
    ) -> tuple[str | None, S3BackupPageResponse | None]:
        """Push current DB to S3."""
        cfg = self._load()
        ok, msg = push_backup(self._db_path, cfg)
        from urllib.parse import quote

        if ok:
            return f"/admin/s3-backup?msg={quote(msg)}", None
        return None, self.render_page(org=org, theme=theme, error=msg)

    def handle_pull(
        self, *, org: dict[str, Any], theme: str, db_path: str
    ) -> tuple[str | None, S3BackupPageResponse | None]:
        """Pull latest.db from S3 and restore it."""
        import sqlite3

        from hoa_accounting.web.database_admin_pages import DatabaseAdminPages

        cfg = self._load()
        ok, msg, data = pull_backup(cfg)
        if not ok:
            return None, self.render_page(org=org, theme=theme, error=msg)
        # Reuse existing restore logic (validates SQLite file, runs migrations)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            admin_pages = DatabaseAdminPages(conn, db_path=db_path)
            redirect_url, form_resp, error_msg = admin_pages.handle_restore(
                data, org=org, theme=theme
            )
        finally:
            conn.close()
        if redirect_url:
            return redirect_url, None
        # handle_restore returned an error page — show our wrapper instead
        return None, self.render_page(
            org=org, theme=theme, error=error_msg or "Restore from S3 failed."
        )
