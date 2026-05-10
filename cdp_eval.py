"""CDP로 특정 탭에 JS 평가 후 결과 출력"""

import json
import sys
import websocket
import urllib.request


def get_tab(filter_url=None, target_id=None):
    tabs = json.loads(urllib.request.urlopen("http://localhost:9223/json").read())
    if target_id:
        for t in tabs:
            if t["id"] == target_id:
                return t
    for t in tabs:
        if t.get("type") != "page":
            continue
        if filter_url is None or filter_url in t.get("url", ""):
            return t
    return None


def eval_js(target_id, expr, timeout=20):
    tab = get_tab(target_id=target_id)
    if not tab:
        return {"error": "no tab"}
    ws = websocket.create_connection(
        tab["webSocketDebuggerUrl"], timeout=timeout, suppress_origin=True
    )
    msg = {
        "id": 1,
        "method": "Runtime.evaluate",
        "params": {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": True,
        },
    }
    ws.send(json.dumps(msg))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == 1:
            ws.close()
            return resp.get("result")


def navigate(target_id, url, wait_ms=3000):
    tab = get_tab(target_id=target_id)
    if not tab:
        return {"error": "no tab"}
    ws = websocket.create_connection(
        tab["webSocketDebuggerUrl"], timeout=20, suppress_origin=True
    )
    ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
    ws.recv()
    ws.send(json.dumps({"id": 2, "method": "Page.navigate", "params": {"url": url}}))
    ws.recv()
    import time

    time.sleep(wait_ms / 1000.0)
    ws.close()


if __name__ == "__main__":
    cmd = sys.argv[1]
    target = sys.argv[2]
    arg = sys.argv[3] if len(sys.argv) > 3 else None
    if cmd == "eval":
        print(json.dumps(eval_js(target, arg), ensure_ascii=False, indent=2))
    elif cmd == "nav":
        navigate(target, arg)
        print("navigated")
    elif cmd == "tabs":
        tabs = json.loads(urllib.request.urlopen("http://localhost:9223/json").read())
        for t in tabs:
            if t.get("type") == "page":
                print(t["id"], t["url"][:120])
