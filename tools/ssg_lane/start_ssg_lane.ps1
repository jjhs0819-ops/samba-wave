# SSG 추가 레인 기동 — 주거용 프록시 IP 하나를 SSG 수집에 더 붙인다.
#
# 배경
#   SSG(Akamai)는 서버·프록시 직접 HTTP·TLS 위장까지 전부 403 으로 막고
#   실제 브라우저만 통과시킨다(2026-08-06 실측: python·curl_cffi 전 IP 403,
#   같은 프록시 IP라도 크롬은 200). 그래서 SSG 처리량은 "브라우저를 띄운
#   IP 개수"에 묶인다. 프록시 설정은 크롬 프로세스 단위라 IP 하나당
#   크롬 인스턴스를 따로 띄워야 한다.
#
# 로컬 중계기를 쓰는 이유
#   크롬 --proxy-server 는 URL 의 id:pw 를 무시하고 인증창을 띄우고,
#   MV3 확장앱은 blocking webRequest 가 막혀 자동응답이 불가하다.
#   그래서 인증 없는 로컬 프록시를 열어 상위로 넘길 때만 인증을 붙인다.
#   중계기는 CONNECT 를 그대로 relay 만 한다 — TLS 를 가로채면 지문이 바뀌어
#   SSG 가 차단하므로 절대 복호화하지 않는다.
#
# 사용: powershell -File start_ssg_lane.ps1
#   -RelayPort  로컬 중계 포트 (기본 18101)
#   -DebugPort  크롬 CDP 포트 (기본 9401)
#   -Upstream   상위 프록시 host:port
param(
  [int]$RelayPort = 18101,
  [int]$DebugPort = 9401,
  [string]$Upstream = "119.206.200.126:6014",
  [string]$ProxyUser = "smart-zhej55fgrt0k",
  [string]$ProxyPass = "keGU2DZxflfM3QJj",
  [string]$ApiUrl = "https://api.samba-wave.co.kr"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$relay = Join-Path $root "proxy_relay.py"
$ext = "C:\Users\canno\workspace\samba-wave\extension"
$profileDir = "C:\Users\canno\AppData\Local\samba-ssg-lane\$DebugPort"

New-Item -ItemType Directory -Force -Path $profileDir | Out-Null

# 1) 중계기 — 이미 떠 있으면 재사용
$relayUp = $false
try {
  $c = New-Object Net.Sockets.TcpClient
  $c.Connect("127.0.0.1", $RelayPort); $relayUp = $true; $c.Close()
} catch { $relayUp = $false }

if (-not $relayUp) {
  Start-Process "python" -ArgumentList @($relay, $RelayPort, $Upstream, $ProxyUser, $ProxyPass) -WindowStyle Hidden
  Start-Sleep -Seconds 3
  Write-Host "[SSG레인] 중계기 기동: 127.0.0.1:$RelayPort -> $Upstream"
} else {
  Write-Host "[SSG레인] 중계기 이미 실행 중 ($RelayPort)"
}

# 2) 크롬(웨일) — 이미 그 CDP 포트로 떠 있으면 재사용
$browserUp = $false
try {
  Invoke-WebRequest "http://127.0.0.1:$DebugPort/json/version" -UseBasicParsing -TimeoutSec 3 | Out-Null
  $browserUp = $true
} catch { $browserUp = $false }

if ($browserUp) {
  Write-Host "[SSG레인] 브라우저 이미 실행 중 (CDP $DebugPort)"
  exit 0
}

$exe = (Get-Process whale -ErrorAction SilentlyContinue | Select-Object -First 1).Path
if (-not $exe) { $exe = "C:\Program Files\Naver\Naver Whale\Application\whale.exe" }
if (-not (Test-Path $exe)) { throw "웨일 실행파일을 찾을 수 없음: $exe" }

# 이미지·GPU 끄기 — 상세 페이지를 렌더링하지 않고 HTML 만 fetch 하므로 불필요.
Start-Process $exe -ArgumentList @(
  "--remote-debugging-port=$DebugPort",
  "--user-data-dir=$profileDir",
  "--proxy-server=http://127.0.0.1:$RelayPort",
  "--load-extension=$ext",
  "--disable-extensions-except=$ext",
  "--blink-settings=imagesEnabled=false",
  "--disable-gpu",
  "--disable-background-timer-throttling",
  "--no-first-run", "--no-default-browser-check",
  "about:blank"
)
Start-Sleep -Seconds 12
Write-Host "[SSG레인] 브라우저 기동 (CDP $DebugPort, 프로필 $profileDir)"
Write-Host "[SSG레인] 확장앱 팝업에서 백엔드 주소($ApiUrl)와 키를 넣고 SSG 를 체크하세요."
Write-Host "[SSG레인] 신규 deviceId 는 서버 '분담' 화면에서 SSG 로 배정해야 잡이 갑니다."
