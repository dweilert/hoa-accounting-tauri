"""Startup backup service — creates a timestamped SQLite copy at app launch.

Reads config from the 'backup' key in the app config dict:
  backup:
    dir: /path/to/backups      # required
    max_keep: 10               # optional, default 10
    s3_bucket: my-bucket       # optional; if set, also uploads to S3
    s3_prefix: db-backups/     # optional, default 'db-backups/'
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_MAX_KEEP = 10
_FILENAME_PREFIX = "hoa_accounting_"
_FILENAME_GLOB = f"{_FILENAME_PREFIX}*.db"


class BackupService:
    def __init__(self, db_path: str, backup_config: dict) -> None:
        self._db_path = db_path
        self._backup_dir = Path(backup_config.get("dir", "backups")).expanduser()
        self._max_keep = int(backup_config.get("max_keep", _DEFAULT_MAX_KEEP))
        self._s3_bucket = (backup_config.get("s3_bucket") or "").strip()
        self._s3_prefix = (backup_config.get("s3_prefix") or "db-backups/").rstrip("/") + "/"

    def run(self, conn: sqlite3.Connection) -> str | None:
        """Create a backup, rotate old ones, upload to S3 if configured.

        Returns the backup filename on success, or None if backup dir isn't configured.
        Errors are logged but never raised — a backup failure must not prevent startup.
        """
        if not self._backup_dir or str(self._backup_dir) == "backups":
            return None
        try:
            return self._do_run(conn)
        except Exception:
            log.exception("Startup backup failed — app will continue without backup")
            return None

    def _do_run(self, conn: sqlite3.Connection) -> str:
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"{_FILENAME_PREFIX}{ts}.db"
        dest_path = self._backup_dir / filename

        dest_conn = sqlite3.connect(str(dest_path))
        try:
            conn.backup(dest_conn)
        finally:
            dest_conn.close()

        file_size = dest_path.stat().st_size

        try:
            conn.execute(
                """INSERT INTO startup_backups (backed_up_at, file_path, file_size_bytes)
                   VALUES (datetime('now'), ?, ?)""",
                (str(dest_path), file_size),
            )
            conn.commit()
        except Exception:
            log.warning("Could not record backup metadata to startup_backups table", exc_info=True)

        self._rotate_local()

        if self._s3_bucket:
            self._upload_s3(dest_path, filename)

        log.info("Startup backup written: %s (%.1f MB)", dest_path, file_size / 1_048_576)
        return filename

    def _rotate_local(self) -> None:
        backups = sorted(self._backup_dir.glob(_FILENAME_GLOB))
        while len(backups) > self._max_keep:
            oldest = backups.pop(0)
            try:
                oldest.unlink()
                log.debug("Rotated old backup: %s", oldest)
            except OSError:
                log.warning("Could not delete old backup: %s", oldest)

    def _upload_s3(self, local_path: Path, filename: str) -> None:
        try:
            import boto3  # type: ignore[import]
            s3 = boto3.client("s3")
            key = self._s3_prefix + filename
            s3.upload_file(str(local_path), self._s3_bucket, key)
            log.info("Backup uploaded to s3://%s/%s", self._s3_bucket, key)
            self._rotate_s3()
        except Exception:
            log.exception("S3 backup upload failed — local backup retained")

    def _rotate_s3(self) -> None:
        try:
            import boto3  # type: ignore[import]
            s3 = boto3.client("s3")
            paginator = s3.get_paginator("list_objects_v2")
            objects = []
            for page in paginator.paginate(Bucket=self._s3_bucket, Prefix=self._s3_prefix):
                objects.extend(
                    o for o in page.get("Contents", []) if o["Key"].endswith(".db")
                )
            objects.sort(key=lambda o: o["Key"])
            while len(objects) > self._max_keep:
                key = objects.pop(0)["Key"]
                s3.delete_object(Bucket=self._s3_bucket, Key=key)
                log.debug("Rotated S3 backup: %s", key)
        except Exception:
            log.warning("S3 backup rotation failed", exc_info=True)
