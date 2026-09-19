#!/usr/bin/env bash
# Cloud Agent install: idempotent repo bootstrap after checkout.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

export PATH="${HOME}/.local/bin:${PATH}"

if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="${HOME}/.local/bin:${PATH}"
fi

./scripts/bootstrap.sh

if [[ -f apps/web/package-lock.json ]]; then
    (cd apps/web && npm ci)
else
    (cd apps/web && npm install)
fi
