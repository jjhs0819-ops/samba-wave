"""페이지의 fetch을 가로채서 응답 total을 직접 읽기."""

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


send("Runtime.enable")
send("Page.enable")
send("Page.navigate", {"url": "https://samba-wave.vercel.app/samba/products"})
time.sleep(5)

# fetch 가로채기 설치
evaluate(
    """
(() => {
  if (window.__fetchHooked) return 'already';
  window.__fetchHooked = true;
  window.__captured = [];
  const orig = window.fetch.bind(window);
  window.fetch = async function(...args) {
    const url = (args[0] && args[0].url) || args[0];
    const resp = await orig(...args);
    if (typeof url === 'string' && url.includes('products/scroll')) {
      try {
        const clone = resp.clone();
        const j = await clone.json();
        window.__captured.push({
          url,
          total: j.total,
          items_count: (j.items||[]).length,
          first: j.items && j.items[0] ? {id: j.items[0].id, has_ai: (j.items[0].tags||[]).includes('__ai_image__')} : null
        });
      } catch {}
    }
    return resp;
  };
  return 'installed';
})()
"""
)
time.sleep(0.5)

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
  }, 300);
})()
"""
)

time.sleep(4)

r = evaluate("JSON.stringify(window.__captured)")
val = r.get("result", {}).get("result", {}).get("value", "[]")
arr = json.loads(val)
print(f"\n=== captured fetches ({len(arr)}) ===")
for c in arr:
    print(f"url: {c['url'][:150]}")
    print(f"  total={c['total']}, items={c['items_count']}, first={c['first']}")
