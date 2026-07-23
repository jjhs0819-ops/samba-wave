# 비활성 리스팅 복구 루틴 정기 실행 래퍼.
#
# 컨테이너 /tmp 는 주기적으로 비워지므로 매번 스크립트를 다시 넣고 실행한다.
# 로그는 날짜별로 남겨 무엇이 언제 되살아났는지 추적한다.
#
# 작업 스케줄러 등록 예:
#   schtasks /Create /TN "samba-revive-inactive" /SC DAILY /ST 10:00 ^
#     /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\canno\workspace\samba-wave\samba-tools\ebay_sourcing\run_revive.ps1"

param(
    [switch]$Dry  # 실제 등록 없이 대상만 확인
)

$ErrorActionPreference = "Stop"
$Container = "local-samba-api-1"
$Script    = "$PSScriptRoot\revive_inactive.py"
$LogDir    = "$PSScriptRoot\logs"
$Stamp     = Get-Date -Format "yyyy-MM-dd_HHmm"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$Log = "$LogDir\revive_$Stamp.log"

# 컨테이너가 떠 있을 때만 실행 (배포 중이면 조용히 종료)
$running = docker ps --format "{{.Names}}" | Select-String -SimpleMatch $Container
if (-not $running) {
    "[$Stamp] 컨테이너 미기동 — 건너뜀" | Tee-Object -FilePath $Log
    exit 0
}

docker cp $Script "${Container}:/tmp/revive_inactive.py" | Out-Null

# $args 는 PowerShell 예약 변수라 덮어쓰면 스크립트가 죽는다 → 다른 이름 사용
$pyArgs = @("/app/backend/.venv/bin/python3", "/tmp/revive_inactive.py")
if ($Dry) { $pyArgs += "--dry" }

$out = docker exec $Container @pyArgs 2>&1
$out | Where-Object { $_ -match "^(비활성|DRY|RUN|SKIP|NOSRC|   복구완료|   실패)" } |
    Tee-Object -FilePath $Log

# 복구 건수 요약 (모니터링용)
$revived = ($out | Select-String -Pattern "복구완료").Count
"[$Stamp] 복구 $revived 건" | Tee-Object -FilePath $Log -Append
