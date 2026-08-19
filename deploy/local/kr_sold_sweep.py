# -*- coding: utf-8 -*-
"""한국발 판매완료 전수 스윕 — 시드 키워드(a~z,0~9) × 카테고리.

eBay 검색은 키워드가 필수라 한 글자 시드로 근사 전수조사를 한다.
위치 필터는 LH_LocatedIn=1&_salic=196 (advanced search 폼에서 실측한 파라미터.
LH_SALocatedIn 은 무시되니 쓰지 말 것).

출력: C:/tmp/kr_sold_sweep.jsonl (한 줄 = 판매완료 1건)
사용: python3 kr_sold_sweep.py <탭ID> [카테고리ID들 콤마구분]
"""

import io
import json
import os
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn  # noqa: E402

OUT = "C:/tmp/kr_sold_sweep.jsonl"
SEEDS = list("abcdefghijklmnopqrstuvwxyz0123456789")
# 메타 카테고리: id → 이름
CATS = {
    "1": "Collectibles",
    "220": "Toys & Hobbies",
    "64482": "Sports Mem/Cards",
    "26395": "Health & Beauty",
    "11450": "Clothing & Acc",
    "293": "Electronics",
    "11233": "Music",
    "45100": "Entertainment Mem",
    "550": "Art",
    "14339": "Crafts",
    "1281": "Pet Supplies",
    "619": "Musical Instr",
    "281": "Jewelry & Watches",
    "11700": "Home & Garden",
    "888": "Sporting Goods",
    "267": "Books & Magazines",
}


def main():
    tab = sys.argv[1]
    cats = dict(CATS)
    if len(sys.argv) > 2:
        want = set(sys.argv[2].split(","))
        cats = {k: v for k, v in CATS.items() if k in want}

    # [중요] 웹소켓 연결은 카테고리마다 새로 연다.
    # 한 연결로 수백 번 navigate 하면 이벤트가 쌓여 응답이 밀리고,
    # 어느 순간부터 그 카테고리의 시드 전체가 WebSocketTimeoutException 으로
    # 통째로 빠진다(실측: Music 36시드 전멸, 새 연결로 찌르면 즉시 응답).
    state = {"c": None}

    def reconnect():
        try:
            if state["c"]:
                state["c"].close()
        except Exception:
            pass
        state["c"] = CDPConn(tab)
        state["c"].call("Runtime.enable")
        state["c"].call("Page.enable")

    reconnect()

    def js(e):
        r = state["c"].call("Runtime.evaluate", {"expression": e, "returnByValue": True})
        return r.get("result", {}).get("result", {}).get("value")

    seen = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            try:
                seen.add(json.loads(line)["url"])
            except Exception:
                pass
    fh = open(OUT, "a", encoding="utf-8")

    total_new = 0
    for cat_id, cat_name in cats.items():
        reconnect()  # 카테고리 시작마다 새 연결
        cat_new = 0
        err_streak = 0
        for seed in SEEDS:
            url = (
                f"https://www.ebay.com/sch/i.html?_nkw={seed}&_sacat={cat_id}"
                f"&LH_Sold=1&LH_Complete=1&LH_LocatedIn=1&_salic=196&_sop=13&_ipg=240"
            )
            try:
                state["c"].send("Page.navigate", {"url": url})
                time.sleep(9)
                # [중요] 카드형(s-card) 레이아웃은 앵커 href 가 전부 sch/i.html 이라
                # URL 로 중복제거하면 모든 항목이 1건으로 합쳐진다(실측).
                # 고유키는 li 의 data-listingid 를 쓴다.
                rows = js(
                    """JSON.stringify([...document.querySelectorAll('li.s-item, li.s-card')].map(li=>{
                      var t=(li.querySelector('.s-item__title,.s-card__title')||{}).innerText||'';
                      var p=(li.querySelector('.s-item__price,.s-card__price')||{}).innerText||'';
                      var d=(li.innerText.match(/Sold\\s+[A-Z][a-z]{2}\\s+\\d+,\\s*\\d{4}/)||[''])[0];
                      var lid=li.getAttribute('data-listingid')||'';
                      var a=li.querySelector('a[href*="/itm/"]');
                      if(!lid&&a){var m=(a.getAttribute('href')||'').match(/itm\\/(\\d+)/);if(m)lid=m[1];}
                      return {t:t.replace(/\\nOpens in a new window or tab/,'').trim(),p:p.trim(),d:d,u:lid};
                    }).filter(o=>o.t&&o.t!=='Shop on eBay'&&o.u))"""
                ) or "[]"
                for it in json.loads(rows):
                    if it["u"] in seen:
                        continue
                    seen.add(it["u"])
                    fh.write(json.dumps({
                        "cat": cat_name, "seed": seed, "title": it["t"],
                        "price": it["p"], "sold": it["d"], "url": it["u"],
                    }, ensure_ascii=False) + "\n")
                    cat_new += 1
                err_streak = 0
            except Exception as e:
                print(f"  ERR {cat_name}/{seed}: {type(e).__name__}", flush=True)
                err_streak += 1
                if err_streak >= 2:  # 연속 실패 = 연결 오염 → 즉시 재연결
                    reconnect()
                    err_streak = 0
                time.sleep(3)
        fh.flush()
        total_new += cat_new
        print(f"[{cat_name}] 신규 {cat_new}건 (누적 {total_new})", flush=True)
    fh.close()
    print(f"완료 — 총 {total_new}건 -> {OUT}", flush=True)
    try:
        state["c"].close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
