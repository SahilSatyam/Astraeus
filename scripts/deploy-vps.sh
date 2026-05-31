#!/usr/bin/env bash
# Manual deploy script for when you want to deploy without CI.
# Usage: VPS_HOST=your-server.example.com ./scripts/deploy-vps.sh
set -euo pipefail

VPS_HOST="${VPS_HOST:?Set VPS_HOST}"
VPS_USER="${VPS_USER:-deploy}"

echo "==> Deploying to ${VPS_HOST}..."
ssh "${VPS_USER}@${VPS_HOST}" << 'EOF'
  cd /opt/astraeus
  docker compose -f compose.prod.yml pull
  docker compose -f compose.prod.yml up -d --remove-orphans
  docker image prune -f
  echo "==> Deploy complete"
EOF
