#!/usr/bin/env bash
# 로컬 개발환경 한 번에 실행 — Windows Terminal 탭 3개로 분리
# 사용: ./start-local.sh

ROOT="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$ROOT/scripts"

chmod +x "$SCRIPTS"/*.sh 2>/dev/null

GITBASH="C:\\Program Files\\Git\\bin\\bash.exe"

wt.exe \
  new-tab --title "cloud-sql-proxy" "$GITBASH" "$SCRIPTS/run-proxy.sh" \; \
  new-tab --title "backend"         "$GITBASH" "$SCRIPTS/run-backend.sh" \; \
  new-tab --title "frontend"        "$GITBASH" "$SCRIPTS/run-frontend.sh"
