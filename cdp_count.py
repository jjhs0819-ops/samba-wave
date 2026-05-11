"""검색 후 화면 카운트 직접 읽기."""

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


def send(method, params=None):
    mid[0] += 1
    ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid[0]:
            return msg


def evaluate(expr, await_promise=False):
    return send(
        "Runtime.evaluate",
        {"expression": expr, "awaitPromise": await_promise, "returnByValue": True},
    )


send("Page.enable")
send("Page.navigate", {"url": "https://samba-wave.vercel.app/samba/products"})
time.sleep(6)

# 필터 설정 + 검색
evaluate(
    """
(() => {
  function setNative(el, val) {
    const proto = Object.getPrototypeOf(el);
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, val);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  const selects = Array.from(document.querySelectorAll('select'));
  const siteSel = selects.find(s => Array.from(s.options).some(o => o.value === 'SSG'));
  if (siteSel) setNative(siteSel, 'SSG');
  const aiSel = selects.find(s => Array.from(s.options).some(o => o.value === 'ai_img_no'));
  if (aiSel) setNative(aiSel, 'ai_img_no');
  const txtInput = Array.from(document.querySelectorAll('input[type="text"]')).find(i => i.placeholder && i.placeholder.includes('검색어'));
  if (txtInput) setNative(txtInput, '나이');
  setTimeout(() => {
    const btns = Array.from(document.querySelectorAll('button'));
    const searchBtn = btns.find(b => b.textContent.trim() === '검색');
    if (searchBtn) searchBtn.click();
  }, 500);
})()
"""
)

time.sleep(3)

# 화면에서 상품관리 (xxx개) 표시 읽기
r = evaluate(
    """
(() => {
  const text = document.body.innerText;
  const m = text.match(/상품관리\\s*\\(\\s*([\\d,]+)\\s*개\\s*\\)/);
  const cards = document.querySelectorAll('[class*="ProductCard"], article, [role="article"]');
  // AI이미지 배지 카운트
  const aiBadges = Array.from(document.querySelectorAll('span')).filter(s => s.textContent.trim() === 'AI이미지');
  return {
    countLabel: m ? m[1] : 'not found',
    aiBadgesOnScreen: aiBadges.length,
  };
})()
"""
)
print(
    json.dumps(
        r.get("result", {}).get("result", {}).get("value"), ensure_ascii=False, indent=2
    )
)
