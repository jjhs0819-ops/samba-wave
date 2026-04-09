#!/bin/bash
# git push 전 승인 마커 확인 — 마커 없으면 차단 (exit 2)
MARKER="$CLAUDE_PROJECT_DIR/.push-approved"

if [ ! -f "$MARKER" ]; then
  cat >&2 << 'EOF'
✗ [푸시 차단] .push-approved 마커가 없습니다.
  푸시하려면:
  1. 사용자에게 변경 내용 보고
  2. 사용자가 "푸시해" 승인
  3. touch .push-approved 실행
  4. 그 후 git push 실행
EOF
  exit 2
fi

# 마커 확인됨 → 1회용이므로 삭제 후 통과
rm -f "$MARKER"
exit 0
