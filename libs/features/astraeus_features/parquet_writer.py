"""Cold path Parquet writer — serializes feature DataFrames to partitioned Parquet on MinIO.

Layout:
    s3://astraeus-features/feature_{group}_{name}/feature_definition_hash={h}/
        dt=YYYY-MM-DD/symbol_bucket={0..15}/data.parquet

The writer:
- Accepts a polars DataFrame with columns (symbol, event_ts, knowledge_ts, value, value_version, source_hash)
- Partitions by date (dt) and symbol_bucket (hash of symbol % 16)
- Writes snappy-compressed Parquet with 128MB row groups
- Generates a _manifest.json with partition list, row counts, and lineage hash
- Supports both local filesystem and MinIO (via minio client)
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl
import structlog

if TYPE_CHECKING:
    from minio import Minio

logger = structlog.get_logger("astraeus.features.parquet_writer")

REQUIRED_COLUMNS = frozenset(
    {"symbol", "event_ts", "knowledge_ts", "value", "value_version", "source_hash"}
)
NUM_SYMBOL_BUCKETS = 16
ROW_GROUP_SIZE = 128 * 1024 * 1024  # 128 MB


def _symbol_bucket(symbol: str) -> int:
    """Deterministic bucket assignment: hash of symbol mod 16."""
    h = int(hashlib.md5(symbol.encode(), usedforsecurity=False).hexdigest(), 16)
    return h % NUM_SYMBOL_BUCKETS


def _add_partition_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Add dt and symbol_bucket columns for partitioning."""
    return df.with_columns(
        pl.col("event_ts").dt.date().cast(pl.Utf8).alias("dt"),
        pl.col("symbol")
        .map_elements(lambda s: _symbol_bucket(s), return_dtype=pl.Int32)
        .alias("symbol_bucket"),
    )


def _build_manifest(
    partitions: list[dict[str, Any]],
    definition_hash: str,
    total_rows: int,
) -> dict[str, Any]:
    """Build a _manifest.json payload."""
    lineage_input = json.dumps(partitions, sort_keys=True, default=str)
    lineage_hash = hashlib.sha256(lineage_input.encode()).hexdigest()

    return {
        "created_at": datetime.now(tz=UTC).isoformat(),
        "definition_hash": definition_hash,
        "total_rows": total_rows,
        "num_partitions": len(partitions),
        "lineage_hash": lineage_hash,
        "partitions": partitions,
    }


def write_local(
    df: pl.DataFrame,
    *,
    group: str,
    name: str,
    definition_hash: str,
    base_path: Path,
) -> Path:
    """Write partitioned Parquet to local filesystem.

    Args:
        df: DataFrame with required columns.
        group: Feature group name.
        name: Feature name.
        definition_hash: Hash of the feature definition.
        base_path: Root directory for output.

    Returns:
        Path to the written feature directory.
    """
    _validate_schema(df)
    df = _add_partition_columns(df)

    feature_dir = base_path / f"feature_{group}_{name}" / f"feature_definition_hash={definition_hash}"
    feature_dir.mkdir(parents=True, exist_ok=True)

    partitions: list[dict[str, Any]] = []
    total_rows = 0

    for (dt, bucket), partition_df in df.group_by(["dt", "symbol_bucket"]):
        part_dir = feature_dir / f"dt={dt}" / f"symbol_bucket={bucket}"
        part_dir.mkdir(parents=True, exist_ok=True)

        out_path = part_dir / "data.parquet"
        # Drop partition columns before writing
        write_df = partition_df.drop(["dt", "symbol_bucket"])
        write_df.write_parquet(
            out_path,
            compression="snappy",
            row_group_size=ROW_GROUP_SIZE,
        )

        row_count = len(write_df)
        total_rows += row_count
        partitions.append({
            "dt": str(dt),
            "symbol_bucket": int(bucket),  # type: ignore[arg-type]
            "row_count": row_count,
            "path": str(out_path.relative_to(base_path)),
        })

    # Write manifest
    manifest = _build_manifest(partitions, definition_hash, total_rows)
    manifest_path = feature_dir / "_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

    logger.info(
        "parquet_write_local",
        feature=f"{group}.{name}",
        partitions=len(partitions),
        total_rows=total_rows,
        path=str(feature_dir),
    )

    return feature_dir


def write_minio(
    df: pl.DataFrame,
    *,
    group: str,
    name: str,
    definition_hash: str,
    client: Minio,
    bucket: str = "astraeus-features",
) -> str:
    """Write partitioned Parquet to MinIO (S3-compatible).

    Args:
        df: DataFrame with required columns.
        group: Feature group name.
        name: Feature name.
        definition_hash: Hash of the feature definition.
        client: MinIO client instance.
        bucket: Target bucket name.

    Returns:
        S3 prefix where data was written.
    """
    import io
    import tempfile

    _validate_schema(df)
    df = _add_partition_columns(df)

    # Ensure bucket exists
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)

    prefix = f"feature_{group}_{name}/feature_definition_hash={definition_hash}"
    partitions: list[dict[str, Any]] = []
    total_rows = 0

    for (dt, symbol_bucket), partition_df in df.group_by(["dt", "symbol_bucket"]):
        object_key = f"{prefix}/dt={dt}/symbol_bucket={symbol_bucket}/data.parquet"

        # Drop partition columns before writing
        write_df = partition_df.drop(["dt", "symbol_bucket"])

        # Write to a temporary buffer
        with tempfile.SpooledTemporaryFile(max_size=256 * 1024 * 1024) as tmp:
            write_df.write_parquet(
                tmp,  # type: ignore[arg-type]
                compression="snappy",
                row_group_size=ROW_GROUP_SIZE,
            )
            tmp.seek(0)
            size = tmp.seek(0, 2)
            tmp.seek(0)

            client.put_object(
                bucket_name=bucket,
                object_name=object_key,
                data=tmp,
                length=size,
                content_type="application/octet-stream",
            )

        row_count = len(write_df)
        total_rows += row_count
        partitions.append({
            "dt": str(dt),
            "symbol_bucket": int(symbol_bucket),  # type: ignore[arg-type]
            "row_count": row_count,
            "path": f"s3://{bucket}/{object_key}",
        })

    # Write manifest
    manifest = _build_manifest(partitions, definition_hash, total_rows)
    manifest_bytes = json.dumps(manifest, indent=2, default=str).encode()
    manifest_key = f"{prefix}/_manifest.json"

    client.put_object(
        bucket_name=bucket,
        object_name=manifest_key,
        data=io.BytesIO(manifest_bytes),
        length=len(manifest_bytes),
        content_type="application/json",
    )

    logger.info(
        "parquet_write_minio",
        feature=f"{group}.{name}",
        partitions=len(partitions),
        total_rows=total_rows,
        bucket=bucket,
        prefix=prefix,
    )

    return f"s3://{bucket}/{prefix}"


def _validate_schema(df: pl.DataFrame) -> None:
    """Validate that the DataFrame has the required columns."""
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        msg = f"DataFrame missing required columns: {sorted(missing)}"
        raise ValueError(msg)
