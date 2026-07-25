"""eBay 리서치(Terapeak) 한국셀러 판매 스윕 [호스트 실행, 웨일 CDP].

무엇을: e-portal 핫키워드 리포트에서 뽑은 키워드로 eBay 리서치를 돌려
        "한국 셀러가 실제로 판매한 양"을 뽑는다. 조달 우위가 있는 아이템만 골라내는 게 목적.

차단 회피 [중요]:
  Page.navigate 로 URL 을 연속으로 갈아끼우면 eBay 봇탐지에 걸려 IP 가 막힌다
  (2026-07-22 실제로 막혀 중단). 그래서 페이지는 한 번만 열고, 이후에는
  검색창에 키워드를 넣고 Research 버튼을 눌러 XHR 로만 갱신한다.
  간격은 기본 50초.

실행:
  backend/.venv/Scripts/python.exe samba-tools/ebay_sourcing/research_sweep.py \
      [--gap 50] [--limit N] [--out research_out.json]
"""

import io
import json
import re
import sys
import time
import urllib.request

import websocket

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CDP = "http://127.0.0.1:9223"
BASE = ("https://www.ebay.com/sh/research?marketplace=EBAY-US&tabName=SOLD"
        "&dayRange=7&categoryId=0&offset=0&limit=50"
        "&sellerCountry=SellerLocation%3A%3A%3AKR&tz=Asia%2FSeoul")
BLOCK = re.compile(r"pardon our interruption|unusual traffic|are you a robot|"
                   r"verify you are a human", re.I)


class Tab:
    def __init__(self):
        self._connect()

    def _connect(self):
        # [중요] ws 가 한 번 끊기면(웨일 재시작/절전/네트워크) 전체 스윕이 죽었다
        # (2026-07-24 12/300 에서 ConnectionResetError). 재연결로 이어가게 한다.
        tabs = json.load(urllib.request.urlopen(f"{CDP}/json/list"))
        pages = [t for t in tabs if t.get("type") == "page"
                 and "ebay.com/sh/research" in (t.get("url") or "")]
        if not pages:
            pages = [t for t in tabs if t.get("type") == "page"
                     and "ebay.com" in (t.get("url") or "")]
        if not pages:
            raise SystemExit("eBay 탭이 없다 — 웨일에서 셀러허브를 먼저 열어라")
        self.ws = websocket.create_connection(
            pages[0]["webSocketDebuggerUrl"], timeout=90, suppress_origin=True)
        self._id = 0
        self.cmd("Page.enable", _retry=False)
        self.cmd("Runtime.enable", _retry=False)

    def cmd(self, method, params=None, _retry=True):
        try:
            self._id += 1
            self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
            while True:
                m = json.loads(self.ws.recv())
                if m.get("id") == self._id:
                    return m
        except Exception:
            if not _retry:
                raise
            # 끊김 → 잠깐 쉬고 재연결 후 1회 재시도
            time.sleep(10)
            self._connect()
            return self.cmd(method, params, _retry=False)

    def js(self, expr):
        r = self.cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                          "awaitPromise": True})
        return (r.get("result", {}).get("result", {}) or {}).get("value")


READ_JS = r"""(() => {
  const body = document.body.innerText || "";
  const blocked = /pardon our interruption|unusual traffic|are you a robot|verify you are a human/i.test(body);
  const num = (re) => { const m = body.match(re); return m ? m[1].replace(/,/g, "") : null; };
  return JSON.stringify({
    blocked,
    len: body.length,
    // [중요] 이 화면은 값이 라벨 "앞"에 온다: "$78.67\nAvg sold price".
    // 라벨 뒤를 읽으면 차트 축 숫자를 주워 엉뚱한 값이 잡힌다(2026-07-23 확인).
    avgPrice: num(/\$?([\d,\.]+)\s*\n\s*Avg sold price/i),
    sellers:  num(/([\d,]+)\s*\n\s*Total sellers/i),
    sellThru: num(/([\d\.]+)%\s*\n\s*Sell-through/i),
    avgShip:  num(/\$?([\d,\.]+)\s*\n\s*Avg shipping/i),
    // 판매건수는 표 상단 "N Results"
    sold:     num(/([\d,]+)\s*\n\s*Results/i),
  });
})()"""

SEARCH_JS = r"""(async () => {
  const kw = %s;
  // [중요] 상단 eBay 전체검색창(id=gh-ac)을 잡으면 리서치 페이지를 벗어나 일반 검색으로 빠진다.
  // 리서치 키워드 입력창은 placeholder 에 keywords/MPN/UPC 가 들어간 input.textbox__control.
  const inp = [...document.querySelectorAll("input.textbox__control")]
      .find(e => e.offsetParent && /keyword|MPN|UPC/i.test(e.placeholder || ""));
  if (!inp) return "NO_INPUT";
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
  setter.call(inp, kw);
  inp.dispatchEvent(new Event("input", {bubbles: true}));
  inp.dispatchEvent(new Event("change", {bubbles: true}));
  // Research 버튼이 안 보이면 엔터로 제출한다(상단 검색버튼 클릭 금지)
  const btn = [...document.querySelectorAll("button")]
      .filter(b => b.offsetParent && b.id !== "gh-search-btn")
      .find(b => /^\s*research\s*$/i.test((b.innerText || "").trim()));
  if (btn) { btn.click(); return "OK"; }
  inp.focus();
  for (const type of ["keydown", "keypress", "keyup"]) {
    inp.dispatchEvent(new KeyboardEvent(type, {key: "Enter", code: "Enter",
      keyCode: 13, which: 13, bubbles: true}));
  }
  return "OK";
})()"""


def main():
    gap = int(sys.argv[sys.argv.index("--gap") + 1]) if "--gap" in sys.argv else 50
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 999
    out_path = (sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv
                else "research_out.json")
    # [중요] 목록 경로는 반드시 --todo 로 명시. 예전에 /tmp 경로 불일치로 옛 목록을
    # 읽어 엉뚱한 67개를 재수집했다(2026-07-24). 기본값도 스크립트 옆 파일로 둔다.
    todo_path = (sys.argv[sys.argv.index("--todo") + 1] if "--todo" in sys.argv
                 else "samba-tools/ebay_sourcing/todo20_full.json")
    todo = json.load(open(todo_path, encoding="utf-8"))[:limit]
    print(f"목록 {todo_path} — {len(todo)}개")

    tab = Tab()
    # 키워드마다 필터 박힌 URL 로 직접 이동하므로 초기 navigate 불필요.
    results, fails = [], 0
    import urllib.parse

    for i, item in enumerate(todo, 1):
        kw = item["kw"]
        # [중요] 페이지 내 검색(Research 버튼)을 쓰면 URL 의 sellerCountry 가 떨어져
        # 전세계 데이터가 잡힌다. UI 에서 잠가도 유지되지 않는다
        # (2026-07-23: 그렇게 모은 66건 전량 폐기). 키워드마다 필터가 박힌 URL 로 직접 이동한다.
        url = BASE + "&keywords=" + urllib.parse.quote_plus(kw)
        tab.cmd("Page.navigate", {"url": url})

        raw, prev_raw, ready = None, None, False
        for _ in range(25):
            time.sleep(2)
            cur = tab.js("location.href") or ""
            if "sellerCountry" not in cur:
                continue
            raw = tab.js(READ_JS)
            if raw and raw == prev_raw:   # 두 번 연속 같으면 로딩 끝
                ready = True
                break
            prev_raw = raw
        if not ready:
            print(f"{i:>3}/{len(todo)} {kw[:34]:34} 로딩실패")
            fails += 1
            if fails >= 5:
                print("연속 실패 5회 — 중단")
                break
            time.sleep(gap)
            continue

        try:
            d = json.loads(raw)
        except Exception:
            d = {}
        if d.get("blocked"):
            print("차단 감지 — 중단")
            break
        if not d.get("sellers"):
            # 페이지는 정상 로드됐는데 지표가 없다 = 한국셀러 판매 0건(유효한 결과).
            # 실패로 세면 연속 0건에서 스윕이 조기 중단된다(2026-07-23).
            fails = 0
            results.append({"cat": item["cat"], "kw": kw, "listings": "0",
                            "sellers": "0", "avg": None, "sellThru": None,
                            "avgShip": None})
            print(f"{i:>3}/{len(todo)} {kw[:34]:34} 한국셀러 없음")
            json.dump(results, open(out_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        else:
            fails = 0
            row = {"cat": item["cat"], "kw": kw, "listings": d.get("sold"),
                   "sellers": d.get("sellers"), "avg": d.get("avgPrice"),
                   "sellThru": d.get("sellThru"), "avgShip": d.get("avgShip")}
            results.append(row)
            print(f"{i:>3}/{len(todo)} {kw[:34]:34} 셀러 {row['sellers']:>4} "
                  f"| 평균가 ${row['avg'] or '-':>8} | 전환 {row['sellThru'] or '-'}%")
            json.dump(results, open(out_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        time.sleep(gap)

    print(f"\n수집 {len(results)}건 → {out_path}")


main()
