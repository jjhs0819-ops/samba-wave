#!/usr/bin/env bash
# 비활성 리스팅 복구 루틴 정기 실행 래퍼.
#
# 컨테이너 /tmp 는 주기적으로 비워지므로 매번 스크립트를 다시 넣고 실행한다.
# 배포/재시작 중이면 조용히 건너뛴다(작업 스케줄러가 매일 도는 것을 전제).
#
# 작업 스케줄러 등록:
#   schtasks /Create /TN "samba-revive-inactive" /SC DAILY /ST 10:00 /F ^
#     /TR "\"C:\Program Files\Git\bin\bash.exe\" -lc \"'/c/Users/canno/workspace/samba-wave/samba-tools/ebay_sourcing/run_revive.sh'\""
#
# 인자: --dry 를 주면 대상만 출력하고 실제 등록은 하지 않는다.

set -u
CONTAINER="local-samba-api-1"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/revive_inactive.py"
LOGDIR="$HERE/logs"
STAMP="$(date +%Y-%m-%d_%H%M)"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/revive_$STAMP.log"

if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER}$"; then
  echo "[$STAMP] 컨테이너 미기동 — 건너뜀" | tee "$LOG"
  exit 0
fi

docker cp "$SCRIPT" "${CONTAINER}:/tmp/revive_inactive.py" >/dev/null 2>&1

MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" /app/backend/.venv/bin/python3 /tmp/revive_inactive.py "$@" 2>/dev/null \
  | grep -E '^(비활성|DRY|RUN|SKIP|NOSRC|   복구완료|   실패)' | tee "$LOG"

REVIVED=$(grep -c '복구완료' "$LOG" 2>/dev/null || echo 0)
echo "[$STAMP] 복구 ${REVIVED}건" | tee -a "$LOG"
