# 집PC 백엔드 배포 한방 — 코드 수정 후 실행 (재빌드 + 재시작 + 헬스체크)
# 사용: cd deploy/local ; .\deploy-local.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$compose = "docker-compose.tunnel.yml"

Write-Host "[1/4] ruff 정리..." -ForegroundColor Cyan
Push-Location ..\..\backend
try {
  .\.venv\Scripts\python.exe -m ruff format . 2>&1 | Select-Object -Last 1
  .\.venv\Scripts\python.exe -m ruff check --fix . 2>&1 | Select-Object -Last 1
} catch { Write-Host "ruff 스킵(에러 무시): $_" -ForegroundColor Yellow }
Pop-Location

Write-Host "[2/4] 이미지 재빌드..." -ForegroundColor Cyan
docker compose --env-file local.env -f $compose build samba-api
if ($LASTEXITCODE -ne 0) { throw "빌드 실패" }

Write-Host "[3/4] 컨테이너 교체 (워커 ON)..." -ForegroundColor Cyan
$env:BG_DISABLE = '0'
docker compose --env-file local.env -f $compose up -d
if ($LASTEXITCODE -ne 0) { throw "기동 실패" }

Write-Host "[4/4] 헬스체크 (최대 90초)..." -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 18; $i++) {
  Start-Sleep -Seconds 5
  try {
    $r = Invoke-RestMethod "http://localhost:8080/api/v1/health" -TimeoutSec 5
    if ($r.status -eq "healthy") { $ok = $true; break }
  } catch {}
}
if ($ok) {
  Write-Host "배포 완료 - 로컬 healthy" -ForegroundColor Green
  try { $ext = Invoke-RestMethod "https://api.samba-wave.co.kr/api/v1/health" -TimeoutSec 15; Write-Host "외부 도메인: $($ext.status)" -ForegroundColor Green } catch { Write-Host "외부 헬스체크 실패(터널/Caddy 확인): $_" -ForegroundColor Yellow }
} else {
  Write-Host "헬스체크 실패 - 로그 확인: docker compose --env-file local.env -f $compose logs samba-api" -ForegroundColor Red
  exit 1
}
