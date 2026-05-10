"""소싱처 5개 × 상품 5개씩 가격 비교 (오토튠 로그 vs 실제 사이트 표시 가격)"""

import json
import sys
import time
import urllib.request
import websocket

sys.stdout.reconfigure(encoding="utf-8")


# 오토튠 로그에서 추출한 상품 (소싱처별 5개) - 마지막 가격변동 결과 = 오토튠이 인식한 원가
SAMPLES = {
    "GSShop": [
        ("1112115252", 56500),
        ("1112112145", 56500),
        ("1112112763", 39400),
        ("1112117221", 126400),
        ("1112110931", 65900),
    ],
    "MUSINSA": [
        ("5182527", 133500),
        ("5282961", 109800),
        ("5311611", 266200),
        ("5049622", 109000),
        ("4737388", 162000),
    ],
    "ABCmart": [
        ("1020116604", 180000),
        ("1020126723", 60200),
        ("1020121582", 68400),
        ("1020121328", 44500),
        ("1010127103", 68400),
    ],
    "LOTTEON": [
        ("LE1217936014", 105300),
        ("LE1218576560", 162900),
        ("LE1217132650", 131400),
        ("LE1217174310", 190200),
        ("LE1217495923", 115000),
    ],
    "SSG": [
        # SSG는 가격변동 로그 0건, 품절 점검 로그 ID 사용 (DB 갱신가 미수록)
        ("1000801176868", None),
        ("1000770413006", None),
        ("1000680550639", None),
        ("1000770413078", None),
        ("1000770413006", None),
    ],
}


URL_TPL = {
    "GSShop": "https://www.gsshop.com/prd/prd.gs?prdid={}",
    "MUSINSA": "https://www.musinsa.com/products/{}",
    "ABCmart": "https://abcmart.a-rt.com/product/products.a-rt?prdtNo={}",
    "LOTTEON": "https://www.lotteon.com/p/product/{}",
    "SSG": "https://www.ssg.com/item/itemView.ssg?itemId={}",
}


def cdp_send(ws, mid, method, params=None):
    msg = {"id": mid, "method": method}
    if params:
        msg["params"] = params
    ws.send(json.dumps(msg))


def cdp_wait(ws, mid):
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == mid:
            return r


def get_or_create_tab(target_url):
    """기존 탭 재사용 또는 새 탭 생성"""
    tabs = json.loads(urllib.request.urlopen("http://localhost:9223/json").read())
    # samba-wave / extensions / 11st / ssg / musinsa 페이지는 건드리지 않음
    # 가격 검증용 별도 탭 1개 사용
    target = None
    for t in tabs:
        if t.get("type") == "page" and "about:blank" in t.get("url", ""):
            target = t
            break
    if not target:
        # 새 탭 생성
        r = json.loads(
            urllib.request.urlopen("http://localhost:9223/json/new?about:blank").read()
        )
        target = r
    return target


def navigate_and_get_text(tab, url, wait_sec=8, eval_expr="document.body.innerText"):
    ws = websocket.create_connection(
        tab["webSocketDebuggerUrl"], suppress_origin=True, timeout=30
    )
    cdp_send(ws, 1, "Page.enable")
    cdp_wait(ws, 1)
    cdp_send(ws, 2, "Page.navigate", {"url": url})
    cdp_wait(ws, 2)
    time.sleep(wait_sec)
    cdp_send(
        ws,
        3,
        "Runtime.evaluate",
        {"expression": eval_expr, "returnByValue": True, "awaitPromise": True},
    )
    r = cdp_wait(ws, 3)
    ws.close()
    val = r.get("result", {}).get("result", {}).get("value", "")
    return val if val is not None else ""


SITE_PRICE_JS = {
    # GSShop: renderJson 데이터 직접 추출 (오토튠 로직과 동일)
    "GSShop": r"""
(async () => {
  const wait = ms => new Promise(r=>setTimeout(r,ms));
  await wait(3000);
  // gsPrc, cpnDcAmt 추출 시도
  let info = {};
  try {
    const w = window;
    if (w.__INITIAL_STATE__) info.state = JSON.stringify(w.__INITIAL_STATE__).slice(0,2000);
  } catch(e){}
  // DOM 가격
  const sel = (s)=>document.querySelector(s)?.innerText?.trim();
  info.title = document.querySelector('h2.prd_name')?.innerText || sel('.prd_name') || document.title;
  info.gsPrice = sel('.prc_amt strong') || sel('.prc strong') || sel('.price strong');
  info.salePrice = sel('strong.prc_amt') || sel('em.prc_amt');
  // 최대혜택가/쿠폰 영역
  info.benefitArea = (document.querySelector('.benefit_area, .prc_total, .prd_price_box')?.innerText||'').slice(0,500);
  return JSON.stringify(info);
})()
""",
    "MUSINSA": r"""
(async () => {
  const wait = ms => new Promise(r=>setTimeout(r,ms));
  await wait(4000);
  const sel = (s)=>document.querySelector(s)?.innerText?.trim();
  const info = {};
  info.title = sel('h2.product_title_section span') || sel('h3') || document.title;
  // 무신사 최대혜택가 영역
  info.priceArea = (document.querySelector('div[class*="price"], section[class*="price"]')?.innerText||'').slice(0,400);
  info.salePrice = sel('span.text-title_18px_semi.text-red') || sel('span[class*="price-final"]') || sel('span[class*="text-red"]');
  info.normalPrice = sel('span[class*="line-through"]');
  return JSON.stringify(info);
})()
""",
    "ABCmart": r"""
(async () => {
  const wait = ms => new Promise(r=>setTimeout(r,ms));
  await wait(3500);
  const sel = (s)=>document.querySelector(s)?.innerText?.trim();
  const info = {};
  info.title = sel('h3.prd-name-detail') || sel('h1') || document.title;
  info.priceArea = (document.querySelector('.prd-price, .price-info, .prd-price-area')?.innerText||'').slice(0,500);
  info.salePrice = sel('.sale-price em') || sel('strong.price') || sel('.price em');
  return JSON.stringify(info);
})()
""",
    "LOTTEON": r"""
(async () => {
  const wait = ms => new Promise(r=>setTimeout(r,ms));
  await wait(5000);
  const sel = (s)=>document.querySelector(s)?.innerText?.trim();
  const info = {};
  info.title = sel('h1, h2.product__name') || document.title;
  info.priceArea = (document.querySelector('.price-info, .product-price, [class*="ProductPrice"]')?.innerText||'').slice(0,600);
  info.salePrice = sel('.price-area .price') || sel('strong.price') || sel('em.price-num');
  return JSON.stringify(info);
})()
""",
}


def main():
    site = sys.argv[1] if len(sys.argv) > 1 else "GSShop"
    samples = SAMPLES.get(site, [])
    if not samples:
        print(f"no samples for {site}")
        return

    def fresh_tab():
        # 매 상품 별 새 탭 생성 (이전 탭은 닫음)
        req = urllib.request.Request(
            "http://localhost:9223/json/new?about:blank", method="PUT"
        )
        return json.loads(urllib.request.urlopen(req).read())

    import re

    # 무신사: 메인 가격은 H1 영역 + .text-red, ABCmart/롯데온도 상품 헤더 영역만 잡음
    expr = '(async()=>{await new Promise(r=>setTimeout(r,9000)); const txt = document.body.innerText.slice(0,6000); const title = (document.querySelector("h1, h2")?.innerText||document.title).slice(0,100); return JSON.stringify({title, head: txt})})()'
    for spid, db_price in samples:
        url = URL_TPL[site].format(spid)
        dbs = f"{db_price:,}" if db_price else "N/A"
        print(f"\n=== {site} {spid} (DB원가={dbs}) ===")
        work_tab = fresh_tab()
        try:
            text = navigate_and_get_text(work_tab, url, wait_sec=1, eval_expr=expr)
            if not isinstance(text, str):
                print("  no text")
                continue
            try:
                obj = json.loads(text)
                head = obj.get("head", "")
                title = obj.get("title", "")
            except Exception:
                head = text[:2500]
                title = ""
            prices = re.findall(r"(\d{1,3}(?:,\d{3})+)\s*원", head)
            unique_prices = []
            for p in prices:
                if p not in unique_prices:
                    unique_prices.append(p)
            print(f"  title: {title[:60]}")
            print(f"  표시 가격 후보 (앞 10개): {unique_prices[:10]}")
        except Exception as e:
            print(f"  ERR: {e}")
        # 탭 닫기
        try:
            urllib.request.urlopen(
                f"http://localhost:9223/json/close/{work_tab['id']}"
            ).read()
        except Exception:
            pass


if __name__ == "__main__":
    main()
