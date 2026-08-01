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
# 확장앱 latest 버전 주입 — extension/manifest.json version → build-arg EXT_VERSION
# → Dockerfile ENV EXTENSION_LATEST_VERSION. 안 하면 백엔드가 fallback 상수를 써서
# 확장앱 자동업데이트 대상 버전이 어긋난다.
try {
  $manifest = Get-Content "..\..\extension\manifest.json" -Raw | ConvertFrom-Json
  $env:EXT_VERSION = "$($manifest.version)"
  Write-Host "확장앱 버전 주입: EXT_VERSION=$($env:EXT_VERSION)" -ForegroundColor Cyan
} catch { Write-Host "manifest 버전 읽기 실패(무시): $_" -ForegroundColor Yellow }
# build 는 build: 섹션 있는 local.yml 로 (tunnel.yml 은 image: 참조라 'No services to build')
docker compose --env-file local.env -f docker-compose.local.yml build samba-api
if ($LASTEXITCODE -ne 0) { throw "빌드 실패" }

Write-Host "[3/4] 컨테이너 교체 (워커 ON)..." -ForegroundColor Cyan
$env:BG_DISABLE = '0'
# up -d 출력을 잡아둔다 — 실패 시 원인(포트충돌/이미지없음/엔진오류)이 여기에만 있고,
# 그냥 throw 하면 유실돼 다음 사람이 원인을 못 찾는다. (2026-08-01 사고)
$upLog = docker compose --env-file local.env -f $compose up -d 2>&1
$upLog | ForEach-Object { Write-Host $_ }
$upFailed = ($LASTEXITCODE -ne 0)

# up -d 가 실패하면 컨테이너가 'Created'(생성만 되고 미기동) 로 남아 프로덕션이 통째로
# 죽는다. 실제로 2026-08-01 배포에서 api/worker/kream/reconciler 4개가 Created 로 남아
# 외부 api.samba-wave.co.kr 이 530 을 반환했다. throw 하고 끝내지 말고 살려낸다.
$svcNames = @(
  'local-samba-api-1', 'local-samba-worker-1',
  'local-samba-kream-1', 'local-samba-reconciler-1',
  'local-caddy-1', 'local-cloudflared-1'
)
$notRunning = @()
foreach ($n in $svcNames) {
  $state = (docker inspect -f '{{.State.Status}}' $n 2>$null)
  if ($LASTEXITCODE -ne 0) { continue }  # 해당 컨테이너 미사용 구성 — 건너뜀
  if ($state -ne 'running') { $notRunning += $n }
}
if ($notRunning.Count -gt 0) {
  Write-Host "미기동 컨테이너 $($notRunning.Count)개 감지: $($notRunning -join ', ')" -ForegroundColor Yellow
  Write-Host "자동 기동 시도..." -ForegroundColor Yellow
  docker start @notRunning 2>&1 | ForEach-Object { Write-Host $_ }
  Start-Sleep -Seconds 5
  $still = @()
  foreach ($n in $notRunning) {
    if ((docker inspect -f '{{.State.Status}}' $n 2>$null) -ne 'running') { $still += $n }
  }
  if ($still.Count -gt 0) {
    Write-Host "!! 기동 실패 — 프로덕션 다운 상태다: $($still -join ', ')" -ForegroundColor Red
    Write-Host "   로그: docker logs $($still[0]) --tail 50" -ForegroundColor Red
    Write-Host "   수동복구: docker start $($still -join ' ')" -ForegroundColor Red
    throw "기동 실패 — 컨테이너 $($still -join ', ') 미기동"
  }
  Write-Host "자동 기동 성공 — 전 컨테이너 running" -ForegroundColor Green
}
if ($upFailed -and $notRunning.Count -eq 0) { throw "기동 실패 (compose 오류, 위 출력 확인)" }

Write-Host "[4/4] 헬스체크 (최대 90초)..." -ForegroundColor Cyan
$ok = $false
$lastErr = $null
for ($i = 0; $i -lt 18; $i++) {
  Start-Sleep -Seconds 5
  try {
    $r = Invoke-RestMethod "http://localhost:8080/api/v1/health" -TimeoutSec 5
    if ($r.status -eq "healthy") { $ok = $true; break }
    $lastErr = "status=$($r.status)"
  } catch { $lastErr = $_.Exception.Message }
}
if ($ok) {
  Write-Host "배포 완료 - 로컬 healthy" -ForegroundColor Green
  try { $ext = Invoke-RestMethod "https://api.samba-wave.co.kr/api/v1/health" -TimeoutSec 15; Write-Host "외부 도메인: $($ext.status)" -ForegroundColor Green } catch { Write-Host "외부 헬스체크 실패(터널/Caddy 확인): $_" -ForegroundColor Yellow }
} else {
  # 여기 도달 = 컨테이너는 running 인데 앱이 응답 안 함(기동 중 예외/마이그레이션 실패 등).
  # 마지막 실패 사유와 앱 로그를 바로 보여준다 — 매번 손으로 logs 치게 만들지 않는다.
  Write-Host "헬스체크 실패 (컨테이너는 running, 앱 미응답)" -ForegroundColor Red
  if ($lastErr) { Write-Host "마지막 오류: $lastErr" -ForegroundColor Red }
  Write-Host "--- samba-api 최근 로그 30줄 ---" -ForegroundColor Red
  docker logs local-samba-api-1 --tail 30 2>&1 | ForEach-Object { Write-Host $_ }
  Write-Host "전체 로그: docker compose --env-file local.env -f $compose logs samba-api" -ForegroundColor Red
  exit 1
}
