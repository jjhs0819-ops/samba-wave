"""Network 응답 본문 캡처 - timing 개선."""

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
results_by_id = {}


def _read_until(predicate, timeout=10.0):
    deadline = time.time() + timeout
    ws.settimeout(0.5)
    while time.time() < deadline:
        try:
            raw = ws.recv()
        except Exception:
            continue
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        if msg.get("id"):
            results_by_id[msg["id"]] = msg
        if predicate(msg):
            ws.settimeout(None)
            return msg
    ws.settimeout(None)
    return None


def send(method, params=None):
    mid[0] += 1
    my_id = mid[0]
    ws.send(json.dumps({"id": my_id, "method": method, "params": params or {}}))
    _read_until(lambda m: m.get("id") == my_id, timeout=10.0)
    return results_by_id.get(my_id)


def evaluate(expr, await_promise=False):
    return send(
        "Runtime.evaluate",
        {"expression": expr, "awaitPromise": await_promise, "returnByValue": True},
    )


send("Network.enable")
send("Runtime.enable")
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
  }, 300);
})()
"""
)

# 응답 본문 가져오기
ws.settimeout(0.3)
target_id = None
finished_ids = []
deadline = time.time() + 8
while time.time() < deadline:
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
        u = msg["params"]["request"]["url"]
        if "products/scroll" in u and "ai_filter=ai_img_no" in u:
            target_id = msg["params"]["requestId"]
            print("[capture] target requestId:", target_id, "url:", u[:200])
    elif (
        method == "Network.responseReceived"
        and msg["params"].get("requestId") == target_id
    ):
        print(
            "[capture] response received, status:",
            msg["params"]["response"].get("status"),
        )
    elif (
        method == "Network.loadingFinished"
        and msg["params"].get("requestId") == target_id
    ):
        finished_ids.append(target_id)
        # 잠시 대기 후 body 요청
        time.sleep(0.5)
        ws.settimeout(None)
        body_resp = send("Network.getResponseBody", {"requestId": target_id})
        body_str = body_resp.get("result", {}).get("body", "")
        if body_str:
            try:
                j = json.loads(body_str)
                print(f"\n=== RESPONSE ===")
                print(f"total: {j.get('total')}")
                print(f"items count: {len(j.get('items', []))}")
                for it in (j.get("items") or [])[:3]:
                    tags = it.get("tags") or []
                    print(
                        f"  id={it.get('id')} site={it.get('source_site')} has_ai_image={'__ai_image__' in tags}"
                    )
                print(f"counts: {j.get('counts')}")
            except Exception as e:
                print("parse error:", e, body_str[:500])
        else:
            print("empty body, full resp:", json.dumps(body_resp, indent=2)[:1000])
        break
        ws.settimeout(0.3)

if not finished_ids:
    print("never finished")
