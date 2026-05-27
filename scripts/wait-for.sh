#!/usr/bin/env bash
# Wait for an HTTP endpoint to return 200, or exit non-zero after timeout.
#
# Usage: scripts/wait-for.sh <url> [timeout_seconds]

set -euo pipefail

url="${1:?usage: wait-for.sh URL [TIMEOUT_SECONDS]}"
timeout="${2:-30}"

deadline=$(( $(date +%s) + timeout ))
while [[ $(date +%s) -lt ${deadline} ]]; do
    if curl -fsS -o /dev/null -w '%{http_code}' "${url}" 2>/dev/null | grep -q '^200$'; then
        echo "OK: ${url}"
        exit 0
    fi
    sleep 1
done

echo "TIMEOUT: ${url} did not return 200 within ${timeout}s" >&2
exit 1
