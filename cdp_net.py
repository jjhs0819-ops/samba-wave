"""CDP로 products 페이지의 fetch 요청 캡처해 ai_filter 파라미터 확인."""

import json
import socket
import base64
import os
import websocket as _ws
import time

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


def send(method, params=None, wait_result=True):
    mid[0] += 1
    ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
    if not wait_result:
        return None
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid[0]:
            return msg


# Network/Runtime 활성화
send("Network.enable")
send("Runtime.enable")

# 페이지 새로고침
send("Page.enable")
send("Page.reload", {"ignoreCache": True}, wait_result=False)

# 이벤트 수집 (10초)
ws.settimeout(0.5)
start = time.time()
requests = []
while time.time() - start < 15:
    try:
        raw = ws.recv()
    except Exception:
        continue
    msg = json.loads(raw)
    if msg.get("method") == "Network.requestWillBeSent":
        url = msg["params"]["request"]["url"]
        if "products/scroll" in url or "ai_filter" in url:
            requests.append(url)

print(f"\n=== captured requests ({len(requests)}) ===")
for u in requests:
    print(u[:300])
