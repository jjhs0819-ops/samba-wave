"""백엔드 API 직접 호출 — ai_filter 적용 여부 검증."""

import json
import socket
import base64
import os
import websocket as _ws
import sys

sys.stdout.reconfigure(encoding="utf-8")

sock = socket.create_connection(("127.0.0.1", 9223))
key = base64.b64encode(os.urandom(16)).decode()
path = "/devtools/page/CD4FE7ADEA963BC13E7CE8F53574A443"
req = (
    f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:9223\r\nUpgrade: websocket\r\n"
    f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
)
sock.sendall(req.encode())
resp = b""
while b"\r\n\r\n" not in resp:
    resp += sock.recv(4096)
ws = _ws.WebSocket()
ws.sock = sock
ws.connected = True

mid = [0]


def send(method, params=None):
    mid[0] += 1
    ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid[0]:
            return msg


# 1) ai_filter=ai_img_no 포함 — 기대: ~125
# 2) ai_filter 없음 — 기대: 1,785
expr = """
(async () => {
  const raw = localStorage.getItem('samba_user');
  const token = raw ? JSON.parse(raw).access_token : null;
  const base = 'https://api.samba-wave.co.kr/api/v1/samba/collector/products/scroll';
  // 페이지의 fetchWithAuth 트리거된 마지막 요청에서 X-Api-Key 값을 알아내야 하지만
  // 간단히 페이지 Window의 process.env가 안 노출되므로, 페이지 자체의 collectorApi.scrollProducts 직접 호출
  // window 객체에서 API_BASE 등 export된 모듈 접근 불가 → fetch interceptor 트릭 사용
  // 가장 간단: 페이지의 collectorApi를 webpack chunk로부터 추출 어려움. → 페이지 fetch 가로채기
  const orig = window.fetch;
  const captured = [];
  window.fetch = async function(...args) {
    captured.push({url: args[0], headers: args[1]?.headers});
    return orig.apply(this, args);
  };
  // 첫 요청 — collectorApi 트리거를 위해 임시 dom 이벤트 발생 어려움
  // 대신 페이지가 이미 갖고 있는 token + X-Api-Key 헤더 추측: env에서 빌드 시 박혔으면 번들에서 찾기
  // Simpler: 페이지에 빌드된 process.env 변수 추출
  const scripts = Array.from(document.scripts).map(s => s.src).filter(Boolean);
  let apiKey = '';
  // 빌드 chunk에서 NEXT_PUBLIC_API_GATEWAY_KEY 추출 시도
  for (const src of scripts.slice(0, 3)) {
    try {
      const r = await orig(src);
      const t = await r.text();
      const m = t.match(/NEXT_PUBLIC_API_GATEWAY_KEY[^"]*"([^"]+)"/) || t.match(/X-Api-Key["'\s:]*([a-zA-Z0-9_-]{20,})/);
      if (m) { apiKey = m[1]; break; }
    } catch {}
  }
  const headers = { 'Authorization': `Bearer ${token}` };
  if (apiKey) headers['X-Api-Key'] = apiKey;
  const a = await fetch(`${base}?skip=0&limit=3&search=%EB%82%98%EC%9D%B4&search_type=name&source_site=SSG&ai_filter=ai_img_no&sort_by=collect-desc`, {headers});
  const aText = await a.text();
  let aj; try { aj = JSON.parse(aText); } catch { aj = {raw: aText.slice(0,500)}; }
  const b = await fetch(`${base}?skip=0&limit=3&search=%EB%82%98%EC%9D%B4&search_type=name&source_site=SSG&sort_by=collect-desc`, {headers});
  const bText = await b.text();
  let bj; try { bj = JSON.parse(bText); } catch { bj = {raw: bText.slice(0,500)}; }
  return {
    aStatus: a.status,
    bStatus: b.status,
    aTotal: aj.total,
    bTotal: bj.total,
    aRaw: aj.raw,
    bRaw: bj.raw,
    aKeys: Object.keys(aj).join(','),
    bKeys: Object.keys(bj).join(','),
    aFirstHasAi: aj.items && aj.items[0] ? (aj.items[0].tags||[]).includes('__ai_image__') : null,
    has_token: !!token,
  };
})()
"""

r = send(
    "Runtime.evaluate",
    {"expression": expr, "awaitPromise": True, "returnByValue": True},
)
print(json.dumps(r, indent=2, ensure_ascii=False)[:3000])
