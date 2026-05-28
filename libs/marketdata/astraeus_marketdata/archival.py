"""MinIO archival service for raw API responses.

Stores raw response bytes from adapters in MinIO (S3-compatible) for
full reproducibility and audit. Each response is stored with metadata
linking it back to the ingestion run and lineage records.

Bucket structure:
  astraeus-raw-responses/
    {source}/{year}/{month}/{day}/{run_id}/{symbol}.json.gz
"""

from __future__ import annotations

import gzip
import io
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import uuid

logger = structlog.get_logger("astraeus.marketdata.archival")

_BUCKET_NAME = "astraeus-raw-responses"


class MinIOArchiver:
    """Archives raw API responses to MinIO object storage.

    Provides full audit trail: any bar can be traced back to the exact
    API response that produced it via the source_response_uri in lineage.
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
    ) -> None:
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._secure = secure
        self._client: object | None = None

    async def _get_client(self) -> object:
        """Lazy-initialize the MinIO client."""
        if self._client is None:
            try:
                from minio import Minio  # noqa: PLC0415

                self._client = Minio(
                    self._endpoint,
                    access_key=self._access_key,
                    secret_key=self._secret_key,
                    secure=self._secure,
                )
                # Ensure bucket exists
                if not self._client.bucket_exists(_BUCKET_NAME):  # type: ignore[union-attr]
                    self._client.make_bucket(_BUCKET_NAME)  # type: ignore[union-attr]
                    logger.info("minio_bucket_created", bucket=_BUCKET_NAME)
            except ImportError:
                logger.warning("minio_not_installed", msg="pip install minio")
                raise
        return self._client

    def _build_object_key(
        self,
        source: str,
        run_id: uuid.UUID,
        symbol: str,
        fetch_date: date,
    ) -> str:
        """Build the S3 object key for a raw response."""
        return (
            f"{source}/{fetch_date.year}/{fetch_date.month:02d}/"
            f"{fetch_date.day:02d}/{run_id}/{symbol}.json.gz"
        )

    async def archive_response(
        self,
        raw_response: bytes,
        source: str,
        run_id: uuid.UUID,
        symbol: str,
        fetch_date: date | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Archive a raw API response to MinIO.

        Args:
            raw_response: Raw bytes from the API response.
            source: Adapter source name (e.g., "yahoo", "polygon").
            run_id: Ingestion run UUID.
            symbol: Primary symbol for this response.
            fetch_date: Date of the fetch (defaults to today).
            metadata: Additional metadata to attach to the object.

        Returns:
            The MinIO URI (s3://{bucket}/{key}) for lineage tracking.
        """
        if fetch_date is None:
            fetch_date = datetime.now(tz=UTC).date()

        client = await self._get_client()
        object_key = self._build_object_key(source, run_id, symbol, fetch_date)

        # Compress the response
        compressed = gzip.compress(raw_response)

        # Build metadata
        obj_metadata = {
            "x-amz-meta-source": source,
            "x-amz-meta-run-id": str(run_id),
            "x-amz-meta-symbol": symbol,
            "x-amz-meta-fetch-date": fetch_date.isoformat(),
            "x-amz-meta-original-size": str(len(raw_response)),
        }
        if metadata:
            obj_metadata.update(metadata)

        # Upload
        data = io.BytesIO(compressed)
        client.put_object(  # type: ignore[attr-defined]
            _BUCKET_NAME,
            object_key,
            data,
            length=len(compressed),
            content_type="application/gzip",
            metadata=obj_metadata,
        )

        uri = f"s3://{_BUCKET_NAME}/{object_key}"

        logger.debug(
            "minio_archived",
            uri=uri,
            original_size=len(raw_response),
            compressed_size=len(compressed),
        )

        return uri

    async def retrieve_response(self, uri: str) -> bytes:
        """Retrieve and decompress a raw response from MinIO.

        Args:
            uri: The s3:// URI returned by archive_response.

        Returns:
            The original uncompressed response bytes.
        """
        client = await self._get_client()

        # Parse URI: s3://bucket/key
        parts = uri.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        key = parts[1]

        response = client.get_object(bucket, key)  # type: ignore[attr-defined]
        try:
            compressed = response.read()
        finally:
            response.close()
            response.release_conn()

        return gzip.decompress(compressed)
