# -*- coding: utf-8 -*-
"""이베이 Terapeak 리서치 — 한국 셀러 필터로 키워드 하나씩 훑기.
15시간에 걸쳐 천천히(호출당 1키워드) — ScheduleWakeup으로 외부에서 페이싱.
결과는 C:/tmp/ebay_sweep_results.jsonl 에 누적(줄당 상품 1건, JSON)."""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn  # noqa: E402

RESULTS_PATH = "C:/tmp/ebay_sweep_results.jsonl"
PROGRESS_PATH = "C:/tmp/ebay_sweep_progress.json"

# 포켓몬 제외, 니치/재현가능 위주 — 카드(비포켓몬)/K팝굿즈/캐릭터굿즈/시계/패션 브랜드
KEYWORDS = [
    # 카드/TCG (포켓몬 제외)
    "yugioh card korean", "one piece card korean", "digimon card korean",
    "weiss schwarz card", "sports card korean", "lorcana card",
    # K-pop 굿즈 (단일 아이템)
    "kpop photocard", "kpop lightstick", "bts photocard", "seventeen photocard",
    "stray kids merch", "newjeans photocard", "aespa photocard", "enhypen merch",
    "kpop album korean", "twice merch", "ive photocard", "riize photocard",
    # 캐릭터/피규어
    "sanrio plush korea", "line friends goods", "kakao friends goods",
    "labubu blind box", "sonny angel korea", "pokemon plush korea",
    "anime figure korea", "nendoroid korea",
    # 패션/신발 (한국 브랜드)
    "mardi mercredi korea", "matin kim korea", "kirsh korea",
    "ader error korea", "gentle monster korea", "covernat korea",
    "musinsa korea", "mlb korea cap",
    # 시계
    "casio korea watch", "g-shock korea",
    # 기타 니치
    "korean stationery", "korean skincare tool", "korean snack box",
]

RESEARCH_URL_TMPL = (
    "https://www.ebay.com/sh/research"
    "?marketplace=EBAY-US"
    "&keywords={kw}"
    "&dayRange=30"
    "&sellerCountry=SellerLocation%3A%3AKR"
    "&sorting=-totalsales"
    "&tabName=SOLD"
    "&offset=0&limit=50"
)


def find_ebay_tab():
    import urllib.request

    resp = urllib.request.urlopen("http://localhost:9223/json", timeout=10)
    tabs = json.loads(resp.read())
    for t in tabs:
        if t.get("type") == "page" and "ebay.com/sh/research" in t.get("url", ""):
            return t["id"]
    for t in tabs:
        if t.get("type") == "page" and "ebay.com" in t.get("url", ""):
            return t["id"]
    return None


def load_progress():
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"done": []}


def save_progress(p):
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)


def scrape_one(keyword):
    from urllib.parse import quote

    tab_id = find_ebay_tab()
    if not tab_id:
        print("ebay 탭 없음")
        return None

    c = CDPConn(tab_id)
    c.call("Page.enable")
    c.call("Runtime.enable")
    url = RESEARCH_URL_TMPL.format(kw=quote(keyword))
    c.send("Page.navigate", {"url": url})
    time.sleep(4)

    js = """
    (() => {
      const tables = [...document.querySelectorAll('table')];
      let best = null, bestRows = -1;
      for (const t of tables) {
        const rc = t.querySelectorAll('tr').length;
        if (rc > bestRows) { best = t; bestRows = rc; }
      }
      if (!best || bestRows < 2) return JSON.stringify({rows: [], count: 0});
      const rows = [...best.querySelectorAll('tr')];
      const header = [...rows[0].children].map(c => c.textContent.trim());
      const idx = (subs) => header.findIndex(h => subs.some(s => h.includes(s)));
      const iT = Math.max(0, idx(['리스팅','Listing']));
      const iP = idx(['판매 가격','Avg sold','Average sold']);
      const iS = idx(['총 판매','Total sold']);
      const iR = idx(['상품 매출','Total sales']);
      const clean = s => (s||'').replace(/\\s+/g,' ').trim();
      const numOf = s => { const m = clean(s).replace(/,/g,'').match(/(\\d+(?:\\.\\d+)?)/); return m ? parseFloat(m[1]) : null; };
      const cellVal = (cell) => { if(!cell) return null; const v = cell.querySelector('div > div') || cell.firstElementChild || cell; return numOf(v.textContent); };
      const out = [];
      rows.slice(1).forEach(r => {
        const c = [...r.children];
        if (c.length < 3) return;
        const a = c[iT] && c[iT].querySelector('a');
        const title = clean(a ? a.textContent : (c[iT] ? c[iT].textContent : ''));
        if (!title) return;
        out.push({
          title,
          price: iP >= 0 ? cellVal(c[iP]) : null,
          sold: iS >= 0 ? cellVal(c[iS]) : null,
          revenue: iR >= 0 ? cellVal(c[iR]) : null,
          url: a ? a.href.split('?')[0] : '',
        });
      });
      return JSON.stringify({rows: out, count: out.length});
    })()
    """
    r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
    val = r.get("result", {}).get("result", {}).get("value", "{}")
    c.close()
    try:
        data = json.loads(val)
    except Exception:
        data = {"rows": [], "count": 0}
    return data


def main():
    progress = load_progress()
    done = set(progress.get("done", []))
    remaining = [k for k in KEYWORDS if k not in done]
    if not remaining:
        print("전체 키워드 완료")
        return
    kw = remaining[0]
    print(f"[sweep] '{kw}' 조회 중... ({len(done)}/{len(KEYWORDS)} 완료)")
    data = scrape_one(kw)
    if data is None:
        print("실패 — 탭 없음, 다음에 재시도")
        return
    rows = data.get("rows", [])
    with open(RESULTS_PATH, "a", encoding="utf-8") as f:
        for row in rows:
            row["keyword"] = kw
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[sweep] '{kw}': {len(rows)}건 저장")
    done.add(kw)
    progress["done"] = list(done)
    save_progress(progress)
    print(f"[sweep] 진행 {len(done)}/{len(KEYWORDS)}")


if __name__ == "__main__":
    main()
