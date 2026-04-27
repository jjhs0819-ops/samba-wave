#!/usr/bin/env bash
# 로컬 백엔드 API 자동 테스트 스크립트
# Claude가 사람 개입 없이 로컬 서버 동작을 검증하는 용도
# 사용: bash backend/scripts/test_local_api.sh [토큰]

set -euo pipefail

BASE="http://localhost:28080"
TOKEN="${1:-}"
PASS=0
FAIL=0
SKIP=0

# 색상
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}✗${NC} $1"; FAIL=$((FAIL+1)); }
skip() { echo -e "${YELLOW}−${NC} $1 (토큰 없음, 스킵)"; SKIP=$((SKIP+1)); }

# 헬퍼: HTTP 상태코드 확인
check_status() {
  local desc="$1" url="$2" expected="${3:-200}"
  local args=()
  [[ -n "$TOKEN" ]] && args+=(-H "Authorization: Bearer $TOKEN")
  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" "${args[@]}" "$url" 2>/dev/null || echo "000")
  if [[ "$status" == "$expected" ]]; then
    pass "$desc → HTTP $status"
  else
    fail "$desc → HTTP $status (기대: $expected)"
  fi
}

# 헬퍼: 응답 body에 키 포함 여부 확인
check_body() {
  local desc="$1" url="$2" keyword="$3"
  local args=()
  [[ -n "$TOKEN" ]] && args+=(-H "Authorization: Bearer $TOKEN")
  local body
  body=$(curl -s "${args[@]}" "$url" 2>/dev/null || echo "")
  if echo "$body" | grep -q "$keyword"; then
    pass "$desc → '$keyword' 포함"
  else
    fail "$desc → '$keyword' 없음 (응답: ${body:0:100})"
  fi
}

echo "═══════════════════════════════════════════"
echo "  삼바웨이브 로컬 API 테스트"
echo "  BASE: $BASE"
echo "═══════════════════════════════════════════"

# ── 1. 서버 기동 확인 ──────────────────────────
echo ""
echo "[ 1. 서버 상태 ]"
if curl -s --max-time 3 "$BASE/api/v1/health" -o /dev/null 2>/dev/null; then
  check_body "health check" "$BASE/api/v1/health" "healthy\|status"
else
  fail "서버 미기동 — localhost:28080 응답 없음"
  echo ""
  echo "  → 백엔드 실행 명령: cd backend && .venv/Scripts/python.exe run.py"
  exit 1
fi

# ── 2. 공개 엔드포인트 ─────────────────────────
echo ""
echo "[ 2. 공개 엔드포인트 ]"
check_status "OpenAPI docs" "$BASE/docs" 200
check_status "OpenAPI JSON" "$BASE/openapi.json" 200

# ── 3. 인증 필요 엔드포인트 ───────────────────
echo ""
echo "[ 3. 인증 엔드포인트 ]"
if [[ -z "$TOKEN" ]]; then
  skip "jobs 목록"
  skip "collector products"
  skip "orders 목록"
  skip "analytics"
else
  check_status "jobs 목록" "$BASE/api/v1/samba/jobs?limit=1" 200
  check_status "collector products" "$BASE/api/v1/samba/collector/products?limit=1" 200
  check_status "orders 목록" "$BASE/api/v1/samba/orders?limit=1" 200
  check_status "analytics" "$BASE/api/v1/samba/analytics/summary" 200
fi

# ── 4. bg-worker 엔드포인트 (워커 토큰) ───────
echo ""
echo "[ 4. BG Worker 엔드포인트 ]"
WORKER_TOKEN="${WORKER_TOKEN:-test-token}"
WS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "X-Worker-Token: $WORKER_TOKEN" \
  "$BASE/api/v1/samba/proxy/bg-jobs/config" 2>/dev/null || echo "000")
if [[ "$WS" == "200" || "$WS" == "403" ]]; then
  pass "bg-jobs/config 응답 → HTTP $WS"
else
  fail "bg-jobs/config → HTTP $WS (기대: 200 또는 403)"
fi

# ── 결과 ──────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════"
echo -e "  결과: ${GREEN}성공 $PASS${NC} | ${RED}실패 $FAIL${NC} | ${YELLOW}스킵 $SKIP${NC}"
echo "═══════════════════════════════════════════"

[[ $FAIL -eq 0 ]] && exit 0 || exit 1
