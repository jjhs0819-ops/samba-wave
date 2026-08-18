"""CDP(Chrome DevTools Protocol) 클라이언트 — websocket-client 라이브러리 기반.
Whale이 --remote-allow-origins 플래그 없이 떠서 Origin 헤더 없는 연결만 허용됨
(suppress_origin=True로 우회). 예전 raw socket 수제 프레이머는 부실해서
mouseWheel 등 응답이 느린 이벤트에서 타임아웃/프레임깨짐이 있었음 — 이걸로 교체."""

import json

import websocket


class CDPConn:
    def __init__(self, tab_id, host="localhost", port=9223, timeout=30):
        url = f"ws://{host}:{port}/devtools/page/{tab_id}"
        self.ws = websocket.WebSocket()
        self.ws.connect(url, suppress_origin=True, timeout=timeout)
        self.ws.settimeout(timeout)
        self._id = 0

    def send(self, method, params=None):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        return mid

    def wait_for_id(self, target_id, max_messages=2000):
        for _ in range(max_messages):
            raw = self.ws.recv()
            if not raw:
                continue
            try:
                d = json.loads(raw)
            except Exception:
                continue
            if d.get("id") == target_id:
                return d
        raise TimeoutError(f"no response for id={target_id}")

    def call(self, method, params=None):
        mid = self.send(method, params)
        return self.wait_for_id(mid)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
