#!/usr/bin/env bash
# Generate TypeScript API client from FastAPI OpenAPI spec.
#
# Prerequisites:
#   - API server running (make dev)
#   - npx available (Node.js installed)
#
# Usage:
#   ./scripts/generate-api-client.sh
#
# This fetches the OpenAPI spec from the running API and generates
# typed fetch wrappers in apps/web/src/lib/generated/

set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
OUTPUT_DIR="apps/web/src/lib/generated"

echo "==> Fetching OpenAPI spec from ${API_URL}/openapi.json"
curl -sS "${API_URL}/openapi.json" -o /tmp/astraeus-openapi.json

echo "==> Generating TypeScript client"
mkdir -p "${OUTPUT_DIR}"

npx openapi-typescript /tmp/astraeus-openapi.json \
  --output "${OUTPUT_DIR}/api-types.ts"

echo "==> Generated: ${OUTPUT_DIR}/api-types.ts"
echo "    Import types from '@/lib/generated/api-types'"
echo ""
echo "    To generate a full client with fetch wrappers:"
echo "    npx openapi-typescript-fetch /tmp/astraeus-openapi.json --output ${OUTPUT_DIR}/client.ts"
