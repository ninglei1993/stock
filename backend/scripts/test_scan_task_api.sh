#!/usr/bin/env bash
# 本地验证扫盘任务 API：GET /api/tasks/scan 与 POST /api/scan/latest
set -euo pipefail
API="${API_BASE:-http://localhost:8000/api}"
TRADE_DATE="${1:-2026-04-17}"

echo "== GET tasks/scan (before) =="
curl -s "${API}/tasks/scan" | python3 -m json.tool

echo ""
echo "== POST scan/latest trade_date=${TRADE_DATE} =="
curl -s -X POST "${API}/scan/latest?trade_date=${TRADE_DATE}" | python3 -m json.tool

echo ""
echo "== Poll tasks/scan (12 x 3s) =="
for i in $(seq 1 12); do
  echo "--- poll #${i} ---"
  curl -s "${API}/tasks/scan" | python3 -m json.tool
  sleep 3
done
