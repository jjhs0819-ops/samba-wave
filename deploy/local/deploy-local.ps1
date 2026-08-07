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

# ── 크림 사이클 대기 가드 [2026-08-04] ───────────────────────────────────────
# 크림 오토튠은 6분짜리 사이클(실순위 확인 → 갱신 → 삭제 → 등록)을 돈다. 컨테이너를
# 교체하면 돌던 사이클이 통째로 죽어 그 회차 작업이 전부 헛것이 된다.
# 실측(2026-08-04): 여러 세션이 배포를 반복해 45분간 완주 0회 — 재고 빠진 입찰이
# 그대로 남아 주문 이행 실패로 이어진다.
# → 사이클이 돌고 있으면 끝날 때까지 기다렸다 배포한다. 어느 세션이 실행하든 적용된다.
#   건너뛰려면: $env:SKIP_KREAM_WAIT = '1'
# [2026-08-04 2차] 대기 600초·로그 12분은 사이클보다 짧아 가드가 무력했다.
# 실측 한 바퀴: 실순위 272초 + 카드처리 747초 + 실행 = 20분 이상.
# → 10분 만에 포기하고 배포해 매번 사이클을 죽였고(완주 0회), 완주해야 나가는
#   슬랙 요약이 3시간 넘게 안 나갔다. 대기 30분 / 로그 40분으로 늘린다.
function Wait-KreamCycle {
  param([int]$MaxSec = 1800)
  # [2026-08-08] 기본 동작 반전 — 이제 기본은 "기다리지 않음".
  # 대기 가드가 배포를 30분씩 막아 긴급 수정 반영이 계속 지연됐다. 매번
  # SKIP_KREAM_WAIT 를 붙이거나 API 컨테이너만 따로 교체하는 우회를 반복하는 것보다
  # 기본을 바꾸는 게 맞다.
  # 크림 사이클 보호가 필요한 배포에서만 KREAM_WAIT=1 로 켠다
  # (등록 실행 중 컨테이너 교체 시 그 회차 등록분이 유실된다 — 2026-08-06 4,206건).
  if ($env:KREAM_WAIT -ne '1') {
    Write-Host "크림 사이클 대기 안 함(기본). 보호하려면 KREAM_WAIT=1" -ForegroundColor DarkGray
    return
  }
  $running = docker ps --filter name=local-samba-kream-1 --format "{{.Names}}" 2>$null
  if (-not $running) { return }
  $t0 = Get-Date
  $waited = $false
  $postWait = $false
  while (((Get-Date) - $t0).TotalSeconds -lt $MaxSec) {
    # 최근 로그에 사이클 시작만 있고 종료(실행ON 요약)가 없으면 진행 중으로 본다
    # 크림통합 로그 전체를 보고 "마지막 줄이 완료 요약(실행ON)인가"로 판정한다.
    # 종전엔 "STAGE 카드처리 시작" 만 패턴에 넣어, 그 앞 실순위 조회(272초) 구간은
    # 감지 자체가 안 됐다.
    $log = docker logs --since 40m local-samba-kream-1 2>&1 | Select-String -Pattern "\[크림통합\]"
    if (-not $log) { break }
    $last = ($log | Select-Object -Last 1).ToString()
    if ($last -match "실행ON") { break }   # 마지막이 요약 = 사이클 끝남
    # [2026-08-06] 등록 실행 중이면 반드시 기다린다.
    # 등록은 '실행ON' 요약보다 앞 단계라 위 조건만으로는 감지되지 않는다. 6,604건을
    # 내보내는 데 10분 넘게 걸리는데, 그 사이 컨테이너를 교체하면 남은 건이 통째로
    # 날아간다(실측 2026-08-06 11:00 KST: 2,398건만 반영, 4,206건 유실).
    if ($last -match "STAGE 실행-등록") {
      if (-not $postWait) {
        Write-Host "   등록 실행 중 — 완료까지 대기(중단하면 등록분이 날아간다)" -ForegroundColor Yellow
        $postWait = $true
      }
    }
    if (-not $waited) {
      Write-Host "크림 사이클 진행 중 — 완주까지 대기(최대 $([int]($MaxSec/60))분)..." -ForegroundColor Yellow
      $waited = $true
    }
    Start-Sleep -Seconds 20
  }
  if ($waited) { Write-Host "크림 사이클 완료 — 배포 진행" -ForegroundColor Green }
}
Wait-KreamCycle

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
# up -d 는 실패했는데 컨테이너는 전부 running 인 경우가 있다(예: 컨테이너 이름 conflict —
# 다른 세션이 동시에 배포하면 발생). 이때 두 갈래로 갈린다:
#   (a) 컨테이너가 방금 빌드한 이미지로 이미 교체됨 → 배포는 사실상 성공. 막으면 오탐.
#   (b) 옛 컨테이너가 그대로 살아있음 → 새 코드가 반영 안 된 채 "정상"으로 보인다. 이게 더 위험.
# 그래서 running 이라는 사실만으로 판단하지 않고, 실제 이미지 ID 를 대조한다.
if ($upFailed) {
  $appCtrs = @(
    'local-samba-api-1', 'local-samba-worker-1',
    'local-samba-kream-1', 'local-samba-reconciler-1'
  )
  $builtId = (docker image inspect -f '{{.Id}}' local-samba-api 2>$null)
  if ($LASTEXITCODE -ne 0 -or -not $builtId) {
    throw "기동 실패 (compose 오류) — 빌드 이미지 확인 불가. 위 출력 확인"
  }
  $stale = @()
  foreach ($n in $appCtrs) {
    $img = (docker inspect -f '{{.Image}}' $n 2>$null)
    if ($LASTEXITCODE -ne 0) { continue }
    if ($img -ne $builtId) { $stale += $n }
  }
  if ($stale.Count -gt 0) {
    Write-Host "!! compose 실패 + 옛 이미지로 동작 중 — 새 코드가 반영되지 않았다:" -ForegroundColor Red
    Write-Host "   $($stale -join ', ')" -ForegroundColor Red
    Write-Host "   재시도: docker compose --env-file local.env -f $compose up -d --force-recreate" -ForegroundColor Red
    throw "기동 실패 — 컨테이너 $($stale -join ', ') 가 옛 이미지로 동작 중(코드 미반영)"
  }
  Write-Host "compose 는 오류를 냈지만(이름 conflict 등) 전 컨테이너가 최신 이미지로 동작 중 — 계속 진행" -ForegroundColor Yellow
}

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
  # [2026-08-06] 호스트 포트 폴백 — Docker Desktop 포트 프록시가 죽으면
  # localhost:8080 이 TCP 만 붙고 바로 끊긴다(앱은 멀쩡). 그 탓에 정상 배포가
  # 매번 exit 1 로 끝나 실패로 오인됐다. 컨테이너 안에서 직접 물어 확인한다.
  if (-not $ok) {
    $inner = docker exec local-samba-api-1 curl -s --max-time 5 http://127.0.0.1:8080/api/v1/health 2>$null
    if ($inner -match '"status"\s*:\s*"healthy"') {
      $ok = $true
      Write-Host "   (호스트 포트 미응답 — 컨테이너 내부 확인으로 통과)" -ForegroundColor DarkGray
      break
    }
  }
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
