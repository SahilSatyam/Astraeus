#!/bin/sh
# Create the canonical Astraeus buckets in MinIO on first boot.
#
# Buckets:
#   astraeus-research   research notebooks, intermediate parquet
#   astraeus-artifacts  MLflow artifacts, model binaries
#   astraeus-data-lake  raw vendor responses, replay archive

set -eu

mc alias set local http://minio:9000 astraeus astraeus123

for bucket in astraeus-research astraeus-artifacts astraeus-data-lake; do
    if ! mc ls "local/${bucket}" >/dev/null 2>&1; then
        mc mb "local/${bucket}"
        mc version enable "local/${bucket}"
    fi
done

echo "MinIO bootstrap complete."
