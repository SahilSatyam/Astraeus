#!/usr/bin/env bash
# Daily database backup to Hetzner Object Storage via rclone
#
# Prerequisites:
#   - rclone configured with a remote named "hetzner-s3" pointing to Hetzner Object Storage
#   - Docker running with the astraeus-postgres-1 container
#
# Cron setup (add to deploy user's crontab on the VPS):
#   0 3 * * * /opt/astraeus/scripts/backup-db.sh >> /var/log/astraeus-backup.log 2>&1
#
# Restore:
#   rclone copy hetzner-s3:astraeus-backups/daily/astraeus-YYYYMMDD-HHMMSS.dump /tmp/
#   docker exec -i astraeus-postgres-1 pg_restore -U astraeus -d astraeus --clean /tmp/astraeus-YYYYMMDD-HHMMSS.dump
#
set -euo pipefail

BACKUP_DIR="/tmp/astraeus-backups"
DATE=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="astraeus-${DATE}.dump"
REMOTE="hetzner-s3:astraeus-backups"
RETENTION_DAYS=30

mkdir -p "${BACKUP_DIR}"

echo "==> Dumping database..."
docker exec astraeus-postgres-1 pg_dump -U astraeus -Fc astraeus > "${BACKUP_DIR}/${BACKUP_FILE}"

echo "==> Uploading to object storage..."
rclone copy "${BACKUP_DIR}/${BACKUP_FILE}" "${REMOTE}/daily/"

echo "==> Cleaning old remote backups (>${RETENTION_DAYS} days)..."
rclone delete "${REMOTE}/daily/" --min-age "${RETENTION_DAYS}d"

echo "==> Cleaning local temp..."
rm -f "${BACKUP_DIR}/${BACKUP_FILE}"

echo "==> Backup complete: ${BACKUP_FILE}"
