"""검색 후 백엔드 응답 본문 캡처해 total 확인."""

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
send("Page.enable")
send("Page.reload", {"ignoreCache": True}, wait_result=False)
time.sleep(4)

# 설정 + 검색
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
evaluate(script)

# 응답 받기 위해 대기
ws.settimeout(5)
matched_request_id = None
end = time.time() + 10
while time.time() < end:
    try:
        raw = ws.recv()
    except Exception:
        continue
    try:
        msg = json.loads(raw)
    except Exception:
        continue
    method = msg.get("method")
    if method == "Network.requestWillBeSent":
        url = msg["params"]["request"]["url"]
        if "products/scroll" in url and "ai_filter" in url:
            matched_request_id = msg["params"]["requestId"]
            print("matched URL:", url)
    elif (
        method == "Network.loadingFinished"
        and msg["params"].get("requestId") == matched_request_id
    ):
        # 응답 본문 가져오기
        body_resp = send("Network.getResponseBody", {"requestId": matched_request_id})
        body_str = body_resp.get("result", {}).get("body", "")
        try:
            j = json.loads(body_str)
            print(
                f"\nresponse total={j.get('total')}, items_count={len(j.get('items', []))}"
            )
            if j.get("items"):
                sample = j["items"][0]
                print(f"sample id={sample.get('id')} site={sample.get('source_site')}")
                tags = sample.get("tags") or []
                print(f"  has __ai_image__: {'__ai_image__' in tags}")
        except Exception as e:
            print("parse error:", e, body_str[:500])
        break
