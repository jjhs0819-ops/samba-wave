#!/usr/bin/env bash
# eBay 재고 → DB 역동기화 정기 실행 래퍼.
#
# 재고의 정답은 eBay(셀러센터에서 판매자가 올린 값)다. 이 스크립트가 DB 를 따라오게 하고,
# 재고가 살아났는데 미게시로 죽어 있는 리스팅을 되살린다.
#
# 작업 스케줄러 등록:
#   schtasks /Create /TN "samba-stock-sync" /SC DAILY /ST 09:30 /F ^
#     /TR "\"C:\Program Files\Git\bin\bash.exe\" -lc \"'/c/Users/canno/workspace/samba-wave/samba-tools/ebay_sourcing/run_stock_sync.sh'\""

set -u
CONTAINER="local-samba-api-1"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGDIR="$HERE/logs"
STAMP="$(date +%Y-%m-%d_%H%M)"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/stocksync_$STAMP.log"

if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER}$"; then
  echo "[$STAMP] 컨테이너 미기동 — 건너뜀" | tee "$LOG"
  exit 0
fi

docker cp "$HERE/sync_stock_from_ebay.py" "${CONTAINER}:/tmp/sync_stock_from_ebay.py" >/dev/null 2>&1
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" /app/backend/.venv/bin/python3 \
  /tmp/sync_stock_from_ebay.py 2>/dev/null \
  | grep -E '^(대상|재고동기화|되살림|   →|완료:)' | tee "$LOG"
