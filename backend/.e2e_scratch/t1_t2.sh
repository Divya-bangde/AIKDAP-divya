#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
BASE=http://127.0.0.1:8001/api/v1
TOKEN=$(python -c "import json; print(json.load(open('login.json'))['access_token'])")
PROJECT_ID=$(cat project_id.txt)

echo "=== T1: create equation plan ==="
curl -s -o plan.json -w "HTTP %{http_code}\n" -X POST "$BASE/research/experiments/from-equation" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d "{\"project_id\":\"$PROJECT_ID\",\"title\":\"Phase 8.0 canonical equation\",\"expression\":\"2 + 3 * 4\"}"
cat plan.json; echo
PLAN_ID=$(python -c "import json; print(json.load(open('plan.json'))['id'])")
echo "PLAN_ID=$PLAN_ID"

echo "=== T2: execute baseline variant ==="
curl -s -o job.json -w "HTTP %{http_code}\n" -X POST "$BASE/research/experiments/$PLAN_ID/execute" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"variant_id":"baseline"}'
cat job.json; echo
JOB_ID=$(python -c "import json; print(json.load(open('job.json'))['id'])")
echo "JOB_ID=$JOB_ID"
echo "$JOB_ID" > job_id.txt
echo "$PLAN_ID" > plan_id.txt
