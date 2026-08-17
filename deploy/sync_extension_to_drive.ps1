# 확장앱(extension/) → 구글드라이브 동기화.
#
# 각 PC 는 구글드라이브로 동기화된 폴더를 "압축해제된 확장 프로그램"으로 물고 있다.
# 즉 이 복사가 곧 배포다. 여기가 막히면 백엔드 latest 버전만 올라가고 현장 PC 는
# 옛 확장앱을 계속 쓴다.
#
# [2026-08-18] 이 스크립트가 아예 없어서 post-commit 훅이 13일간 조용히 실패했다
# (2026-08-05 2.14.69 이후 2.14.70~75 가 어느 PC 에도 전달 안 됨). 훅은 실패해도
# "무시"로 넘어가므로 아무도 몰랐다. 재발 방지로 실패 시 종료코드를 남긴다.

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$src = Join-Path $repoRoot 'extension'

if (-not (Test-Path $src)) {
  Write-Host "[sync-ext] 원본 없음: $src" -ForegroundColor Red
  exit 1
}

# 드라이브 루트명이 한글('내 드라이브')이라 경로를 코드에 박으면 안 된다.
# Windows PowerShell 5.1 은 .ps1 을 ANSI 로 읽어 한글 리터럴이 깨지고
# Test-Path 가 항상 false 가 된다(2026-08-18 실측 — skip 으로 조용히 통과).
# 그래서 루트만 훑어 'extension' 하위 폴더를 직접 찾는다.
$roots = @('G:\', 'H:\', "$env:USERPROFILE\Google Drive")
$dst = $null
foreach ($r in $roots) {
  if (-not (Test-Path $r)) { continue }
  $hit = Get-ChildItem $r -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName 'extension' } |
    Where-Object { Test-Path (Join-Path $_ 'manifest.json') } |
    Select-Object -First 1
  if (-not $hit -and (Test-Path (Join-Path $r 'extension\manifest.json'))) {
    $hit = Join-Path $r 'extension'
  }
  if ($hit) { $dst = $hit; break }
}
if (-not $dst) {
  Write-Host "[sync-ext] 구글드라이브 경로를 못 찾음 — skip" -ForegroundColor Yellow
  exit 0
}

$srcVer = (Get-Content (Join-Path $src 'manifest.json') -Raw | ConvertFrom-Json).version
$dstVer = if (Test-Path (Join-Path $dst 'manifest.json')) {
  (Get-Content (Join-Path $dst 'manifest.json') -Raw | ConvertFrom-Json).version
} else { '(없음)' }

# /MIR — 드라이브 쪽에 남은 옛 파일까지 정리(삭제된 스크립트가 계속 로드되는 사고 방지).
robocopy $src $dst /MIR /NFL /NDL /NJH /NJS /NP /XD .git | Out-Null

# robocopy 종료코드: 0~7 정상(8 이상만 실패). 0=변경없음, 1=복사됨, 2=여분삭제 등.
if ($LASTEXITCODE -ge 8) {
  Write-Host "[sync-ext] 복사 실패 (robocopy $LASTEXITCODE)" -ForegroundColor Red
  exit 1
}

$newVer = (Get-Content (Join-Path $dst 'manifest.json') -Raw | ConvertFrom-Json).version
if ($newVer -ne $srcVer) {
  Write-Host "[sync-ext] 버전 불일치 — 원본 $srcVer / 드라이브 $newVer" -ForegroundColor Red
  exit 1
}

Write-Host "[sync-ext] 완료: $dstVer -> $newVer  ($dst)" -ForegroundColor Green
exit 0
