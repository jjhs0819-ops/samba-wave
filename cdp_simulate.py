"""실제 사용자 흐름 시뮬레이션 — 필터 설정 후 ai_filter 적용 확인."""

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


def evaluate(expr, await_promise=False):
    return send(
        "Runtime.evaluate",
        {"expression": expr, "awaitPromise": await_promise, "returnByValue": True},
    )


send("Network.enable")
send("Runtime.enable")

# 필터 설정 - React 18 controlled input 트리거
script = """
(async () => {
  function setNative(el, val) {
    const proto = Object.getPrototypeOf(el);
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, val);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  // 모든 select 찾기
  const selects = Array.from(document.querySelectorAll('select'));
  const inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'));
  console.log('selects:', selects.length, 'inputs:', inputs.length);
  // 각 select의 옵션 목록
  return selects.map(s => ({
    options: Array.from(s.options).map(o => ({v: o.value, t: o.text}))
  }));
})()
"""

r = evaluate(script, await_promise=True)
print(
    json.dumps(
        r.get("result", {}).get("result", {}).get("value", []),
        ensure_ascii=False,
        indent=2,
    )[:2000]
)
