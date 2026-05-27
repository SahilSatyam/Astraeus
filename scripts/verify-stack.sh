#!/usr/bin/env bash
# Smoke-check the local stack after `make dev`.
#
# Probes every public endpoint and asserts the expected response shape. Fails
# loudly so CI / first-run feedback catches a half-broken stack early.

set -euo pipefail

api_url="${ASTRAEUS_API_URL:-http://localhost:8000}"

ok() { echo "  OK   $*"; }
fail() { echo "  FAIL $*" >&2; exit 1; }

require_endpoint() {
    local url="$1" expected_status="$2"
    local actual
    actual=$(curl -fsS -o /dev/null -w '%{http_code}' "${url}" 2>/dev/null || true)
    if [[ "${actual}" != "${expected_status}" ]]; then
        fail "${url} returned ${actual} (expected ${expected_status})"
    fi
    ok "${url} -> ${actual}"
}

echo "== API =="
require_endpoint "${api_url}/healthz" 200
require_endpoint "${api_url}/version" 200
require_endpoint "${api_url}/metrics" 200
require_endpoint "${api_url}/readyz" 200

echo "== Observability =="
require_endpoint "http://localhost:16686/" 200
require_endpoint "http://localhost:9090/-/healthy" 200
require_endpoint "http://localhost:3000/api/health" 200

echo
echo "Stack is healthy."
