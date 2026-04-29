"""Storage backend protocol and implementations for PDF report delivery.

The ``StorageBackend`` protocol lets the batch PDF service stay decoupled
from any specific storage provider.  Swap S3 for another provider by
passing a different implementation — no changes to the batch service needed.

Implementations
---------------
S3StorageBackend   — uploads to AWS S3; works locally (access-key env vars)
                     and on AWS Amplify / Lambda (IAM role, no key needed).
LocalFileBackend   — writes files to a local directory; useful for dev/testing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """Upload a PDF and return a reference URL or path string."""

    def upload(
        self, key: str, pdf_bytes: bytes, *, content_type: str = "application/pdf"
    ) -> str:
        """Store *pdf_bytes* under *key* and return a reference to it."""
        ...

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object whose key starts with *prefix*.

        Used by the batch PDF service to ensure only the latest report
        for a given lot lives in storage — stale year/owner-name files
        get cleared before the new upload. Returns the number of keys
        deleted (best-effort; missing prefix is not an error).
        """
        ...


class S3StorageBackend:
    """Upload PDFs to an AWS S3 bucket.

    Credentials are resolved by boto3 in priority order:
      1. Explicit ``aws_access_key_id`` / ``aws_secret_access_key`` (dev)
      2. Environment variables AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
      3. IAM instance/task role (Amplify, Lambda, EC2 — no config needed)

    This means the same code works locally with a .env file and in AWS
    with zero credential config.
    """

    def __init__(
        self,
        bucket: str,
        region: str,
        *,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        presigned_expiry: int = 3600,
    ) -> None:
        import boto3

        self._bucket = bucket
        self._presigned_expiry = presigned_expiry
        self._s3 = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=aws_access_key_id or os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=aws_secret_access_key
            or os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )

    def upload(
        self, key: str, pdf_bytes: bytes, *, content_type: str = "application/pdf"
    ) -> str:
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=pdf_bytes,
            ContentType=content_type,
        )
        url: str = self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=self._presigned_expiry,
        )
        return url

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object under *prefix*. Paginates so >1000 keys work."""
        deleted = 0
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            contents = page.get("Contents") or []
            if not contents:
                continue
            objs = [{"Key": obj["Key"]} for obj in contents]
            self._s3.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": objs, "Quiet": True},
            )
            deleted += len(objs)
        return deleted


class LocalFileBackend:
    """Write PDFs to a local directory (dev / testing)."""

    def __init__(self, output_dir: str | Path) -> None:
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def upload(
        self, key: str, pdf_bytes: bytes, *, content_type: str = "application/pdf"
    ) -> str:
        dest = self._dir / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(pdf_bytes)
        return str(dest)

    def delete_prefix(self, prefix: str) -> int:
        """Delete every file under self._dir whose key starts with *prefix*.

        Mirrors S3 semantics: a prefix is a literal key prefix, not a
        glob — ``owner-reports/L-1/`` removes everything inside that
        sub-directory.
        """
        deleted = 0
        # Treat prefix that ends in '/' as a directory; otherwise match
        # any path whose relative-to-_dir str startswith() the prefix.
        if prefix.endswith("/"):
            target_dir = self._dir / prefix.rstrip("/")
            if target_dir.is_dir():
                for f in target_dir.rglob("*"):
                    if f.is_file():
                        f.unlink()
                        deleted += 1
        else:
            for f in self._dir.rglob("*"):
                if not f.is_file():
                    continue
                rel = f.relative_to(self._dir).as_posix()
                if rel.startswith(prefix):
                    f.unlink()
                    deleted += 1
        return deleted


def default_s3_backend() -> S3StorageBackend:
    """Build an S3 backend from environment variables."""
    bucket = os.environ.get("S3_BUCKET_NAME", "mmpoa-owner-reports")
    region = os.environ.get("AWS_REGION", "us-east-1")
    return S3StorageBackend(bucket=bucket, region=region)
