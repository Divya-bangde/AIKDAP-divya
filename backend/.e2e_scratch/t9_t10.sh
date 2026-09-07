#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
BASE=http://127.0.0.1:8001/api/v1
TOKEN=$(python -c "import json; print(json.load(open('login.json'))['access_token'])")
PROJECT_ID=$(cat project_id.txt)

echo "=== T9: syntactically-malformed (but charset-safe) expression ==="
curl -s -o plan_bad.json -w "HTTP %{http_code}\n" -X POST "$BASE/research/experiments/from-equation" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d "{\"project_id\":\"$PROJECT_ID\",\"title\":\"Phase 8.0 invalid expression\",\"expression\":\"(2 + 3\"}"
cat plan_bad.json; echo
