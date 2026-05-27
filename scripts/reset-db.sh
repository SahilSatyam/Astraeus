#!/usr/bin/env bash
# Reset the local Postgres data volume. Destructive.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

read -r -p "This destroys the local Postgres volume. Continue? [y/N] " confirm
case "${confirm}" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 0 ;;
esac

docker compose -f infra/docker/compose.yml -f infra/docker/compose.override.yml \
    rm -fsv postgres
docker volume rm astraeus_pgdata 2>/dev/null || true

echo "DB volume removed. Run 'make dev' to bring it back up."
