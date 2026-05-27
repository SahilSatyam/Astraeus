#!/usr/bin/env bash
# First-time setup. Idempotent.
#
# - Copies .env.example -> .env if missing.
# - Verifies uv is installed (fails with a friendly hint if not).
# - Pins Python 3.12 via uv and syncs the workspace.
# - Optionally installs pre-commit hooks.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

if ! command -v uv >/dev/null 2>&1; then
    cat <<'EOF' >&2
uv is not installed. Install it first:
  curl -LsSf https://astral.sh/uv/install.sh | sh
or follow https://docs.astral.sh/uv/getting-started/installation/
EOF
    exit 1
fi

if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "Copied .env.example -> .env"
fi

uv python install 3.12 >/dev/null
uv sync --all-packages

if command -v pre-commit >/dev/null 2>&1; then
    pre-commit install --install-hooks >/dev/null || true
elif uv run --quiet pre-commit --version >/dev/null 2>&1; then
    uv run pre-commit install --install-hooks >/dev/null || true
fi

cat <<'EOF'

Bootstrap complete. Next steps:

  make dev        # bring up the local stack
  make smoke      # verify stack health
  make test       # run unit tests

EOF
