"""풀 시뮬레이션: 새로고침 → SSG/나이/AI 선택 → 검색 클릭 → 요청 캡처."""

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


def drain():
    ws.settimeout(0.2)
    msgs = []
    while True:
        try:
            r = ws.recv()
            msgs.append(json.loads(r))
        except Exception:
            break
    ws.settimeout(None)
    return msgs


def get_scroll_urls(msgs):
    return [
        m["params"]["request"]["url"]
        for m in msgs
        if m.get("method") == "Network.requestWillBeSent"
        and "products/scroll" in m.get("params", {}).get("request", {}).get("url", "")
    ]


send("Network.enable")
send("Runtime.enable")
send("Page.enable")
send("Page.reload", {"ignoreCache": True}, wait_result=False)
time.sleep(4)
drain()

# Step A: SSG + AI + 검색어 모두 설정 후 검색 클릭
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
  // 소싱처(SSG) select 찾기 — option value에 'SSG' 있음
  const siteSel = selects.find(s => Array.from(s.options).some(o => o.value === 'SSG'));
  if (siteSel) setNative(siteSel, 'SSG');
  // AI select 찾기
  const aiSel = selects.find(s => Array.from(s.options).some(o => o.value === 'ai_img_no'));
  if (aiSel) setNative(aiSel, 'ai_img_no');
  // 검색어 input — placeholder에 '검색어' 또는 type=text
  const txtInput = Array.from(document.querySelectorAll('input[type="text"]')).find(i => i.placeholder && i.placeholder.includes('검색어'));
  if (txtInput) setNative(txtInput, '나이');
  return {
    site: siteSel ? siteSel.value : 'NA',
    ai: aiSel ? aiSel.value : 'NA',
    q: txtInput ? txtInput.value : 'NA',
  };
})()
"""
r = evaluate(script)
print("setup:", r.get("result", {}).get("result", {}).get("value"))
time.sleep(1)
msgs1 = drain()
print(f"\n=== after dropdown set (auto-apply) ===")
for u in get_scroll_urls(msgs1):
    print(u)

# 응답 본문 가져오기 위해 Network.responseReceived/loadingFinished 감시
# Step B: 검색 버튼 클릭
click_script = """
(() => {
  const btns = Array.from(document.querySelectorAll('button'));
  const searchBtn = btns.find(b => b.textContent.trim() === '검색');
  if (!searchBtn) return 'not found';
  searchBtn.click();
  return 'clicked';
})()
"""
r = evaluate(click_script)
print("\nsearch click:", r.get("result", {}).get("result", {}).get("value"))
time.sleep(2)
msgs2 = drain()
print(f"\n=== after 검색 click ===")
for u in get_scroll_urls(msgs2):
    print(u)
