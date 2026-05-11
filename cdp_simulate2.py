"""실제 사용자 흐름 풀 시뮬레이션 — 필터 설정 후 ai_filter 적용 확인."""

import json
import socket
import base64
import os
import websocket as _ws
import time
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


def send(method, params=None, wait_result=True):
    mid[0] += 1
    ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
    if not wait_result:
        return None
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid[0]:
            return msg


def evaluate(expr, await_promise=False):
    return send(
        "Runtime.evaluate",
        {"expression": expr, "awaitPromise": await_promise, "returnByValue": True},
    )


send("Network.enable")
send("Runtime.enable")

# Step 1: 페이지를 새로고침해서 깨끗한 상태로
send("Page.enable")
send("Page.reload", {"ignoreCache": True}, wait_result=False)
time.sleep(4)

# 큐 비우기
ws.settimeout(0.2)
while True:
    try:
        ws.recv()
    except Exception:
        break
ws.settimeout(None)

# Step 2: AI 드롭다운만 변경 (ai_img_no)
script = """
(() => {
  function setNative(el, val) {
    const proto = Object.getPrototypeOf(el);
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, val);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  const selects = Array.from(document.querySelectorAll('select'));
  // ai 드롭다운 찾기 - 'ai_img_no' option 가진 select
  const aiSel = selects.find(s => Array.from(s.options).some(o => o.value === 'ai_img_no'));
  if (!aiSel) return { error: 'aiSel not found', count: selects.length };
  setNative(aiSel, 'ai_img_no');
  return { applied: aiSel.value };
})()
"""
r = evaluate(script)
print("AI dropdown change:", r.get("result", {}).get("result", {}).get("value"))

# Step 3: 대기 (디바운스 300ms + fetch)
time.sleep(2)

# 그동안 발생한 scroll 요청 수집
ws.settimeout(0.2)
urls = []
while True:
    try:
        raw = ws.recv()
    except Exception:
        break
    try:
        msg = json.loads(raw)
    except Exception:
        continue
    if msg.get("method") == "Network.requestWillBeSent":
        u = msg["params"]["request"]["url"]
        if "products/scroll" in u:
            urls.append(u)

print(f"\n=== AI 변경 후 scroll 요청 ({len(urls)}) ===")
for u in urls:
    print(u)
