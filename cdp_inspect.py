"""웨일 CDP로 products 탭의 fetch 호출과 React 상태 확인."""

import json
import websocket

WS = "ws://127.0.0.1:9223/devtools/page/CD4FE7ADEA963BC13E7CE8F53574A443"

import websocket as _ws

_ws._handshake._get_handshake_headers = _ws._handshake._get_handshake_headers
# 직접 raw 소켓으로 핸드셰이크하여 Origin 헤더 누락
import socket, base64, os

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
print("HS:", resp.split(b"\r\n")[0])
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


# JavaScript: 현재 aiFilter / appliedAiFilter 값을 알 수 없으므로
# 직접 fetch 시도 → 네트워크 결과 확인
expr = """
(async () => {
  // 토큰은 cookie 또는 localStorage에서 가져옴
  const url = '/api/v1/samba/collector/products/scroll?skip=0&limit=5&search=%EB%82%98%EC%9D%B4&search_type=name&source_site=SSG&ai_filter=ai_img_no&sort_by=collect-desc';
  const res = await fetch(url, { credentials: 'include' });
  const data = await res.json();
  return { status: res.status, total: data.total, sample_tags: (data.items||[]).slice(0,3).map(x=>({id:x.id, tags:x.tags})) };
})()
"""

r = send(
    "Runtime.evaluate",
    {"expression": expr, "awaitPromise": True, "returnByValue": True},
)
print(json.dumps(r, indent=2, ensure_ascii=False)[:3000])
ws.close()
