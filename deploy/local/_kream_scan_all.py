# -*- coding: utf-8 -*-
"""크림 공개 브랜드 목록에서 상품 전량 수집 (스크롤 + 응답 가로채기).

왜 이 방식인가:
  - 파트너 API search_products 는 페이지네이션이 없어 상위 50개 고정
  - 페이지 컨텍스트 fetch 는 api.kream.co.kr 로 CORS 차단
  → 페이지가 스스로 보내는 /api/fetch/brands/ 응답을 CDP 로 가로챈다
"""
import sys, os, time, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab = sys.argv[1]
out_path = sys.argv[2]
max_sec = int(sys.argv[3]) if len(sys.argv) > 3 else 600

c = CDPConn(tab)
c.call("Network.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
pending = {}
found = {}
t0 = time.time()
last_new = time.time()
c.send("Runtime.evaluate", {"expression": "window.scrollTo(0, document.body.scrollHeight)"})

while time.time() - t0 < max_sec:
    try:
        c.ws.settimeout(2); msg = c.ws.recv()
    except Exception:
        c.send("Runtime.evaluate", {"expression": "window.scrollBy(0, 6000)"})
        if time.time() - last_new > 45:
            break
        continue
    try:
        d = json.loads(msg)
    except Exception:
        continue
    m = d.get("method")
    if m == "Network.responseReceived":
        if "/api/fetch/brands/" in d["params"]["response"].get("url", ""):
            pending[d["params"]["requestId"]] = 1
    elif m == "Network.loadingFinished" and d["params"]["requestId"] in pending:
        rid = d["params"]["requestId"]; pending.pop(rid, None)
        r = c.call("Network.getResponseBody", {"requestId": rid})
        res = r.get("result", {})
        b = (res.get("result") or res).get("body")
        if not b:
            continue
        for pid, nm in re.findall(r'\\"product_id\\":(\d+),\\"product_name_en\\":\\"([^"]{0,90})', b):
            if pid not in found:
                found[pid] = nm
                last_new = time.time()
        c.send("Runtime.evaluate", {"expression": "window.scrollBy(0, 6000)"})
        if len(found) % 500 < 60:
            print(f"  수집 {len(found)}", flush=True)

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(found, f, ensure_ascii=False)
print("총 수집:", len(found), "->", out_path)
c.close()
