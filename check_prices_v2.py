"""소싱처별 정확한 cost 추출 (오토튠 동일 로직 적용)
- GSShop: m.gsshop.com renderJson 인라인 JSON 파싱
- MUSINSA: window.__MSS__ / __NEXT_DATA__ 또는 API
- ABCmart: in-tab fetch /product/info?prdtNo (XHR)
- LOTTEON: PBF API 또는 DOM 즉시할인
- SSG: domCardPrice DOM 셀렉터
"""

import json
import sys
import time
import urllib.request
import websocket

sys.stdout.reconfigure(encoding="utf-8")


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
}


URL_TPL = {
    "GSShop": "https://m.gsshop.com/prd/prd.gs?prdid={}",
    "MUSINSA": "https://www.musinsa.com/products/{}",
    "ABCmart": "https://abcmart.a-rt.com/product/products.a-rt?prdtNo={}",
    "LOTTEON": "https://www.lotteon.com/p/product/{}",
}


# 페이지 로드 후 가격 추출 JS (각 사이트 코드베이스 로직과 일치)
EXTRACTORS = {
    "GSShop": r"""
(async () => {
  await new Promise(r=>setTimeout(r,5000));
  // m.gsshop.com 페이지의 var renderJson 인라인 JSON에서 추출
  const html = document.documentElement.outerHTML;
  let start = html.indexOf('var renderJson = ');
  if (start < 0) start = html.indexOf('var renderJson=');
  if (start < 0) return JSON.stringify({err:'no renderJson', title:document.title});
  start = html.indexOf('{', start);
  // 균형 맞춰 JSON 추출
  let depth = 0, end = -1;
  for (let i = start; i < html.length; i++) {
    if (html[i] === '{') depth++;
    else if (html[i] === '}') { depth--; if (depth===0) { end = i+1; break; } }
  }
  try {
    const data = JSON.parse(html.slice(start, end));
    const prd = data.prd || {};
    const pmo = data.pmo || {};
    const prc = pmo.prc || {};
    const salePrc = +(prc.salePrc||0);
    const gsPrc = +(pmo.gsPrc||0);
    const flgdPrc = +(prc.flgdPrc||0);
    const cpnDcAmt = +(prc.cpnDcAmt||0);
    const salePrice = gsPrc || flgdPrc || salePrc;
    const cost = (cpnDcAmt > 0) ? (salePrice - cpnDcAmt) : salePrice;
    return JSON.stringify({title: prd.exposPrdNm||prd.prdNm, salePrc, gsPrc, flgdPrc, cpnDcAmt, cost});
  } catch (e) { return JSON.stringify({err: String(e)}); }
})()
""",
    # 무신사: 페이지의 최대혜택가 영역 직접 추출 (로그인 후 표시)
    "MUSINSA": r"""
(async () => {
  await new Promise(r=>setTimeout(r,6000));
  // 무신사 본 상품 가격 영역 (상단 product detail)
  const sels = ['span.text-red.text-title_18px_semi','span[data-mds-component="Typography"][class*="text-red"]','div.text-title_18px_semi.text-red'];
  let priceText = '';
  for (const s of sels) { const el = document.querySelector(s); if (el) { priceText = el.innerText.trim(); break; } }
  // 최대혜택가 라벨 옆 가격
  const labels = Array.from(document.querySelectorAll('span,div,p'));
  let benefit = '';
  for (const el of labels) {
    if (el.innerText && el.innerText.includes('최대혜택가')) {
      const p = el.parentElement;
      const m = (p?.innerText||'').match(/(\d{1,3}(?:,\d{3})+)\s*원/);
      if (m) { benefit = m[1]; break; }
    }
  }
  // 실판매가 (선할인 제외 즉시판매가)
  const finalPrice = (document.querySelector('[class*="price-text"]')?.innerText||'').match(/(\d{1,3}(?:,\d{3})+)/)?.[1] || '';
  const title = document.querySelector('h1, h2, h3')?.innerText || document.title;
  return JSON.stringify({title:title.slice(0,80), priceText, benefit, finalPrice});
})()
""",
    # ABCmart: in-tab fetch (헤더 X-Requested-With 필수)
    "ABCmart": r"""
(async () => {
  const id = location.search.match(/prdtNo=(\d+)/)?.[1];
  if (!id) return JSON.stringify({err:'no prdtNo in URL', url:location.href});
  try {
    const r = await fetch('/product/info?prdtNo='+id, {headers:{'X-Requested-With':'XMLHttpRequest'}, credentials:'include'});
    const d = await r.json();
    const display = +(d.displayProductPrice||0);
    const normal = +((d.productPrice||{}).normalAmt||0);
    const always = +(d.alwaysDscntAmt||0);
    const coupons = (d.maxBenefitCoupon||[]).reduce((s,c)=>s+(+c.dscntAmt||0),0);
    const cost = display - always - coupons;
    return JSON.stringify({title:d.prdtName||d.prdtNm||'', display, normal, always, coupons, cost});
  } catch(e) { return JSON.stringify({err:String(e)}); }
})()
""",
    "LOTTEON": r"""
(async () => {
  await new Promise(r=>setTimeout(r,7000));
  // 즉시할인가 (DOM 우선)
  const sels = [
    '.price-info-area .final-price strong',
    '.product-price strong',
    'em.price-num',
    '.price-area strong',
    'span.price__discount',
  ];
  let dom = '';
  for (const s of sels) { const el = document.querySelector(s); if (el) { dom = el.innerText.trim(); break; } }
  // 페이지 텍스트에서 "즉시할인" 라벨 옆 가격 찾기
  const m = (document.body.innerText.match(/즉시할인[^\n]*?(\d{1,3}(?:,\d{3})+)\s*원/) || [])[1] || '';
  const title = document.querySelector('h2, h1')?.innerText || document.title;
  return JSON.stringify({title:title.slice(0,80), dom, instantDiscount:m});
})()
""",
    "SSG": r"""
(async () => {
  await new Promise(r=>setTimeout(r,6000));
  // domCardPrice 셀렉터
  const sel1 = document.querySelector('.cdtl_new_price.notranslate em.ssg_price');
  const sel2 = document.querySelector('.cdtl_price.point .ssg_price');
  const cardPrice = sel1?.innerText?.trim() || sel2?.innerText?.trim() || '';
  const sellPrice = document.querySelector('.cdtl_old_price em')?.innerText?.trim() || '';
  // bestAmt 정보
  const bestRaw = (document.body.innerText.match(/최적가[^\n]*?(\d{1,3}(?:,\d{3})+)/) || [])[1] || '';
  const title = document.querySelector('.cdtl_info_tit')?.innerText || document.title;
  return JSON.stringify({title:title.slice(0,80), cardPrice, sellPrice, bestAmt:bestRaw});
})()
""",
}


def fresh_tab():
    req = urllib.request.Request(
        "http://localhost:9223/json/new?about:blank", method="PUT"
    )
    return json.loads(urllib.request.urlopen(req).read())


def close_tab(tid):
    try:
        urllib.request.urlopen(f"http://localhost:9223/json/close/{tid}").read()
    except Exception:
        pass


def navigate_eval(tab, url, expr, timeout=40):
    ws = websocket.create_connection(
        tab["webSocketDebuggerUrl"], suppress_origin=True, timeout=timeout
    )
    ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
    ws.recv()
    ws.send(json.dumps({"id": 2, "method": "Page.navigate", "params": {"url": url}}))
    ws.recv()
    time.sleep(0.5)
    ws.send(
        json.dumps(
            {
                "id": 3,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": expr,
                    "returnByValue": True,
                    "awaitPromise": True,
                },
            }
        )
    )
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == 3:
            ws.close()
            return r.get("result", {}).get("result", {}).get("value", "")


def main():
    site = sys.argv[1]
    samples = SAMPLES.get(site, [])
    expr = EXTRACTORS[site]
    for spid, db in samples:
        url = URL_TPL[site].format(spid)
        print(f"\n=== {site} {spid} (DB={db:,}) ===")
        tab = fresh_tab()
        try:
            v = navigate_eval(tab, url, expr)
            print(f"  {v}")
        except Exception as e:
            print(f"  ERR: {e}")
        close_tab(tab["id"])


if __name__ == "__main__":
    main()
