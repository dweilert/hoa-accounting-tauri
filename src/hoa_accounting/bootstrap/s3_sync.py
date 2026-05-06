"""S3 cloud backup/restore service.

Credentials are stored in s3_config.json next to the database file so
non-technical users can configure S3 via the Settings UI without editing
config.yaml by hand.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
_CONFIG_FILENAME = "s3_config.json"
_BACKUP_PREFIX_DEFAULT = "db-backups/"


@dataclass
class S3Config:
    bucket: str = ""
    region: str = "us-east-1"
    access_key_id: str = ""
    secret_access_key: str = ""
    prefix: str = _BACKUP_PREFIX_DEFAULT

    @property
    def is_configured(self) -> bool:
        return bool(self.bucket and self.access_key_id and self.secret_access_key)

    def norm_prefix(self) -> str:
        return self.prefix.rstrip("/") + "/"

    def latest_key(self) -> str:
        return self.norm_prefix() + "latest.db"


def _config_path(db_path: str | Path) -> Path:
    return Path(db_path).parent / _CONFIG_FILENAME


def load_s3_config(db_path: str | Path) -> S3Config:
    """Load S3 config from sidecar JSON, returning defaults if absent."""
    path = _config_path(db_path)
    if not path.exists():
        return S3Config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return S3Config(
            bucket=raw.get("bucket", ""),
            region=raw.get("region", "us-east-1"),
            access_key_id=raw.get("access_key_id", ""),
            secret_access_key=raw.get("secret_access_key", ""),
            prefix=raw.get("prefix", _BACKUP_PREFIX_DEFAULT),
        )
    except Exception:
        log.warning("Could not read S3 config at %s", path, exc_info=True)
        return S3Config()


def save_s3_config(db_path: str | Path, cfg: S3Config) -> None:
    """Persist S3 config to the sidecar JSON file."""
    path = _config_path(db_path)
    path.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")


def _make_client(cfg: S3Config) -> Any:  # type: ignore[return]
    import boto3  # type: ignore[import-untyped]

    return boto3.client(
        "s3",
        region_name=cfg.region,
        aws_access_key_id=cfg.access_key_id,
        aws_secret_access_key=cfg.secret_access_key,
    )


def test_connection(cfg: S3Config) -> tuple[bool, str]:
    """Return (ok, message). Tries head_bucket to verify credentials."""
    if not cfg.is_configured:
        return (
            False,
            "S3 is not configured — enter bucket name, region, and AWS keys first.",
        )
    try:
        s3 = _make_client(cfg)
        s3.head_bucket(Bucket=cfg.bucket)
        return True, f"✓ Connected to s3://{cfg.bucket} in {cfg.region}."
    except Exception as exc:
        return False, f"Connection failed: {exc}"


def list_backups(cfg: S3Config) -> list[dict[str, Any]]:
    """Return up to 20 timestamped backups, newest first."""
    if not cfg.is_configured:
        return []
    try:
        s3 = _make_client(cfg)
        prefix = cfg.norm_prefix()
        paginator = s3.get_paginator("list_objects_v2")
        objects: list[Any] = []
        for page in paginator.paginate(Bucket=cfg.bucket, Prefix=prefix):
            objects.extend(page.get("Contents", []))
        # Only timestamped backups (exclude latest.db)
        backups = [
            o
            for o in objects
            if o["Key"].endswith(".db") and not o["Key"].endswith("/latest.db")
        ]
        backups.sort(key=lambda o: o["Key"], reverse=True)
        result = []
        for o in backups[:20]:
            key_name = o["Key"][len(prefix) :]
            lm = o.get("LastModified")
            date_str = lm.strftime("%Y-%m-%d %H:%M UTC") if lm else ""
            result.append(
                {
                    "key": key_name,
                    "date_str": date_str,
                    "size_mb": round(o["Size"] / 1_048_576, 2),
                }
            )
        return result
    except Exception:
        log.warning("Could not list S3 backups", exc_info=True)
        return []


def push_backup(db_path: str | Path, cfg: S3Config) -> tuple[bool, str]:
    """Upload a consistent snapshot of the DB to S3 as timestamped + latest.db.

    Returns (ok, message).
    """
    if not cfg.is_configured:
        return False, "S3 is not configured."
    db_path = Path(db_path)
    if not db_path.exists():
        return False, "Database file not found."
    tmp_path: Path | None = None
    try:
        # Use SQLite backup API for a consistent snapshot
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(tmp_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        prefix = cfg.norm_prefix()
        timestamped_key = f"{prefix}hoa_accounting_{ts}.db"
        latest_key = cfg.latest_key()

        s3 = _make_client(cfg)
        s3.upload_file(str(tmp_path), cfg.bucket, timestamped_key)
        s3.copy_object(
            Bucket=cfg.bucket,
            CopySource={"Bucket": cfg.bucket, "Key": timestamped_key},
            Key=latest_key,
        )

        size_mb = round(tmp_path.stat().st_size / 1_048_576, 2)
        log.info(
            "Pushed DB to s3://%s/%s (%.2f MB)", cfg.bucket, timestamped_key, size_mb
        )
        return True, (
            f"✓ Backup uploaded to s3://{cfg.bucket}/{timestamped_key} ({size_mb} MB). "
            f"'latest.db' updated."
        )
    except Exception as exc:
        log.exception("S3 push failed")
        return False, f"Upload failed: {exc}"
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def pull_backup(cfg: S3Config) -> tuple[bool, str, bytes]:
    """Download latest.db from S3. Returns (ok, message, file_bytes)."""
    if not cfg.is_configured:
        return False, "S3 is not configured.", b""
    tmp_path: Path | None = None
    try:
        s3 = _make_client(cfg)
        key = cfg.latest_key()
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        s3.download_file(cfg.bucket, key, str(tmp_path))
        data = tmp_path.read_bytes()
        size_mb = round(len(data) / 1_048_576, 2)
        log.info("Pulled DB from s3://%s/%s (%.2f MB)", cfg.bucket, key, size_mb)
        return True, f"Downloaded {size_mb} MB from S3.", data
    except Exception as exc:
        log.exception("S3 pull failed")
        return False, f"Download failed: {exc}", b""
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
