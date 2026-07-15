# 스니덩크↔크림 매칭 반자동 복구 실행기.
# 최신 백업 jsonl 을 컨테이너로 보내고 restore.py 를 돌린다.
# 기본 DRY-RUN(계획만 출력). 실제 복구는 -Apply 붙일 것.
#   미리보기:  pwsh restore.ps1
#   실제복구:  pwsh restore.ps1 -Apply

param([switch]$Apply)
$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path

$latest = Get-ChildItem $dir -Filter "snkr_kream_*.jsonl" |
  Sort-Object Name -Descending | Select-Object -First 1
if (-not $latest) { Write-Error "백업 파일 없음 — 먼저 backup.ps1 실행" }

Write-Host "사용 백업: $($latest.Name)"
docker cp "$($latest.FullName)" local-samba-api-1:/tmp/snkr_backup.jsonl | Out-Null
docker cp (Join-Path $dir "restore.py") local-samba-api-1:/tmp/snkr_restore.py | Out-Null

if ($Apply) {
  docker exec local-samba-api-1 /app/backend/.venv/bin/python /tmp/snkr_restore.py /tmp/snkr_backup.jsonl --apply
} else {
  docker exec local-samba-api-1 /app/backend/.venv/bin/python /tmp/snkr_restore.py /tmp/snkr_backup.jsonl
}
