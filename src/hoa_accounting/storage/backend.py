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


class LocalFileBackend:
    """Write PDFs to a local directory (dev / testing)."""

    def __init__(self, output_dir: str | Path) -> None:
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def upload(
        self, key: str, pdf_bytes: bytes, *, content_type: str = "application/pdf"
    ) -> str:
        dest = self._dir / Path(key).name
        dest.write_bytes(pdf_bytes)
        return str(dest)


def default_s3_backend() -> S3StorageBackend:
    """Build an S3 backend from environment variables."""
    bucket = os.environ.get("S3_BUCKET_NAME", "mmpoa-owner-reports")
    region = os.environ.get("AWS_REGION", "us-east-1")
    return S3StorageBackend(bucket=bucket, region=region)
