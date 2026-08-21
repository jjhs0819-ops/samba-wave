# -*- coding: utf-8 -*-
"""
크림 매칭 시트 자동 동기화.

1) 크림 "구매 내역"(진행중+종료) CDP로 읽기
2) 배송완료 신규건 -> 이베이 A:I 테이블 맨 아래 도착순으로 추가(할인율/원가 계산)
3) 아직 배송완료 안 된 건들 -> K:N 섹션 전체 새로 작성(덮어쓰기)

실행: python kream_ebay_sync.py
"""

import sys
import time
import re
import json

import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn  # noqa: E402

import bunjang_orders as bj  # noqa: E402
import gspread  # noqa: E402

SHEET_ID = "1FM3smmTlsbxhN03CFCoK_Pp5byA9wTfpiQ66jOG0ohM"
TAB_NAME = "크림매칭"
CREDS_PATH = "C:/Users/canno/.claude/google-credentials.json"

CDP_HOST, CDP_PORT = "localhost", 9223

# 시트 글자색 — 카드버전 주문번호를 빨갛게 표시할 때 쓴다.
RED = {"red": 0.8, "green": 0.0, "blue": 0.0}
BLACK = {"red": 0.0, "green": 0.0, "blue": 0.0}

# [2026-08-18] 번개장터 구매건을 같은 K:N 구간에 섞어 넣는다.
# 주문번호 형태로 구분되므로(크림 O-OR…·KPE…, 번장 숫자) 구분 열도, 상태 뒤의
# 출처 꼬리표도 두지 않는다. 다만 "배송 중" 은 크림·번장이 같은 표기라
# 상태 문자열만으로는 순서를 못 가른다 → 주문번호로 출처를 판별해 순위를 매긴다.
STATUS_ORDER = {
    ("kream", "배송 중"): 0,
    ("bunjang", "배송 중"): 1,
    ("kream", "검수합격"): 2,
    ("kream", "입고완료"): 3,
    ("kream", "입고 대기"): 3,
    ("kream", "발송완료"): 4,
    ("bunjang", "배송준비중"): 5,
    ("bunjang", "상품준비중"): 6,
    ("bunjang", "결제완료"): 7,
    ("kream", "대기 중"): 8,
}


def _is_bunjang(order_no):
    """번장 주문번호는 순수 숫자, 크림은 O-OR…/KPE… 형태."""
    return str(order_no).isdigit()


def _sort_key(order_no, status):
    src = "bunjang" if _is_bunjang(order_no) else "kream"
    return STATUS_ORDER.get((src, status), 99)


def find_kream_tab(url_contains):
    import urllib.request

    resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=10)
    tabs = json.loads(resp.read())
    for t in tabs:
        if t.get("type") == "page" and url_contains in t.get("url", ""):
            return t["id"]
    return None


def _open_kream_tab(url):
    """새 kream.co.kr 탭 CDP로 오픈 (/json/new PUT)."""
    import urllib.request

    req = urllib.request.Request(
        f"http://{CDP_HOST}:{CDP_PORT}/json/new?{url}", method="PUT"
    )
    urllib.request.urlopen(req, timeout=10)


def find_any_kream_tabs(n=3, auto_open=False):
    """kream.co.kr 탭 아무거나 n개 — 이전 실행에서 /my/order/xxx로 옮겨져있어도 상관없음.

    auto_open=True면 부족한 만큼 pending/finished 탭을 직접 새로 열어서 채움
    (2026-08-14: 탭이 딴 데로 넘어가있어 P5 실행이 계속 실패하던 문제 — 사람이 매번
    웨일 가서 탭 열 필요 없이 스크립트가 알아서 복구).
    """
    import urllib.request

    def _list():
        resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=10)
        tabs = json.loads(resp.read())
        return [
            t["id"]
            for t in tabs
            if t.get("type") == "page"
            and "kream.co.kr" in t.get("url", "")
            and "partner.kream.co.kr" not in t.get("url", "")
        ]

    ids = _list()
    if auto_open and len(ids) < n:
        fallback_urls = [
            "https://kream.co.kr/my/buying?tab=pending",
            "https://kream.co.kr/my/buying?tab=finished",
        ]
        for i in range(n - len(ids)):
            _open_kream_tab(fallback_urls[i % len(fallback_urls)])
        time.sleep(3)
        ids = _list()
    return ids[:n]


def _scroll_to_load_all(c, max_wheel=60, settle_checks=4):
    """실제 마우스 휠 이벤트로 무한스크롤 끝까지 로드.

    핵심: Page.bringToFront 필수 — 탭이 백그라운드면 휠 이벤트가 현재 활성 탭
    (다른 사이트일 수 있음)으로 새거나 응답이 아예 안 온다(2026-08-13 확인).
    """
    c.call("Page.bringToFront")
    time.sleep(1)
    prev_len = -1
    stable = 0
    for _ in range(max_wheel):
        # [2026-08-21] 휠 이벤트(Input.dispatchMouseEvent) → **JS 스크롤로 교체**.
        # 웨일 창이 최소화·비활성이면 입력 이벤트에 응답을 아예 안 줘서 CDP 호출이
        # 그대로 멎는다(실측: Runtime.evaluate 0.2초 정상 ↔ 휠 무응답 → 타임아웃).
        # 그 탓에 P5 를 눌러도 "체크만 풀리고 아무 일도 안 일어남" 이 반복됐다.
        # window.scrollTo 는 창 상태와 무관하게 동작하고 무한스크롤도 똑같이 걸린다.
        c.call(
            "Runtime.evaluate",
            {
                "expression": "window.scrollTo(0, document.body.scrollHeight)",
                "returnByValue": True,
            },
        )
        time.sleep(0.4)
        r = c.call(
            "Runtime.evaluate",
            {"expression": "document.body.innerText.length", "returnByValue": True},
        )
        cur_len = r.get("result", {}).get("result", {}).get("value", 0) or 0
        if cur_len == prev_len:
            stable += 1
            if stable >= settle_checks:
                break
        else:
            stable = 0
        prev_len = cur_len


def fetch_kream_orders():
    """진행중+종료 탭 전체를 실제 휠스크롤(무한로딩 끝까지)로 읽어옴.

    반환: {order_no: {"date": "26/08/13 14:51", "status": "..."}}
    """
    kream_tabs = find_any_kream_tabs(2, auto_open=True)
    if len(kream_tabs) < 2:
        raise RuntimeError("KREAM 탭 자동 오픈 실패 — 웨일이 꺼져있거나 CDP 연결 안 됨")
    pending_tab, finished_tab = kream_tabs[0], kream_tabs[1]

    all_orders = {}

    for tab_id, label, url in [
        (pending_tab, "pending", "https://kream.co.kr/my/buying?tab=pending"),
        (finished_tab, "finished", "https://kream.co.kr/my/buying?tab=finished"),
    ]:
        c = CDPConn(tab_id)
        c.call("Runtime.enable")
        c.call("Page.enable")
        # [2026-08-21] Input.enable 제거 — 휠 이벤트를 JS 스크롤로 바꿔서 입력 도메인이
        # 필요 없고, 웨일 창이 비활성이면 이 호출 자체가 무응답이라 여기서 멎었다.
        c.send("Page.navigate", {"url": url})
        time.sleep(3)
        _scroll_to_load_all(c)
        r = c.call(
            "Runtime.evaluate",
            {"expression": "document.body.innerText", "returnByValue": True},
        )
        text = r.get("result", {}).get("result", {}).get("value", "") or ""
        c.close()

        blocks = re.split(r"결제번호\s*\n+", text)[1:]
        for b in blocks:
            m_no = re.match(r"\s*(O-OR\d+)", b)
            if not m_no:
                continue
            order_no = m_no.group(1)
            if "잉어킹" not in b and "Magikarp" not in b:
                continue
            m_date = re.search(r"(\d{2}/\d{2}/\d{2} \d{2}:\d{2})", b)
            m_status = re.search(
                r"(발송완료|대기 중|검수합격|입고완료|입고 대기|배송 중|배송완료|취소완료)",
                b,
            )
            all_orders[order_no] = {
                "date": m_date.group(1) if m_date else "",
                "status": m_status.group(1) if m_status else "",
                # 옵션에 "Card Ver." 가 붙은 카드버전 — 시트에서 주문번호를 빨갛게 표시한다
                # (예: "Ungraded A (Card Ver.) / 일반배송")
                "card_ver": "Card Ver." in b,
            }
        print(f"    [{label}] 로드 완료")
    return all_orders


def fetch_price(conn, order_id_numeric):
    """상세페이지에서 최초 결제금액 뽑기. order_id_numeric = 'O-OR' 뒤 숫자.

    conn: 이미 열려있는 CDPConn (탭 하나를 계속 재사용 — 매번 새로 탭 찾으면
    직전 fetch_price가 이미 그 탭을 /my/order/xxx로 옮겨놔서 URL 매칭이 깨짐).
    """
    conn.send(
        "Page.navigate", {"url": f"https://kream.co.kr/my/order/{order_id_numeric}"}
    )
    for wait in (1.8, 1.5, 1.5):  # 로딩 느릴 때 대비 최대 3회(합 4.8초) 재시도
        time.sleep(wait)
        r = conn.call(
            "Runtime.evaluate",
            {"expression": "document.body.innerText", "returnByValue": True},
        )
        text = r.get("result", {}).get("result", {}).get("value", "") or ""
        m = re.search(r"최초 결제금액\s*\n+\s*([\d,]+)원", text)
        if m:
            # 송장 조회는 결제번호(O-OR)가 아니라 주문번호(B-LI)로 한다.
            # 목록에는 B-LI 가 없고 이 상세 화면에만 있어서 같이 뽑아 둔다.
            mb = re.search(r"주문번호\s*B-LI(\d+)", text)
            return m.group(1), (mb.group(1) if mb else "")
    return None, ""


def fetch_tracking(conn, bid_numeric):
    """배송 중인 건의 송장번호 — /api/m/bids/{주문번호} 의 tracking 에서 꺼낸다.

    이 API 는 크림 웹이 인증을 붙여 부르는 것이라 우리가 직접 fetch 하면 막힌다
    (상대경로는 SPA 라 404, 절대경로는 인증이 안 붙는다). 그래서 페이지 로드 전에
    fetch 를 감싸두고, 페이지가 스스로 부른 응답을 가로챈다.

    반환: ("304730174363", "CJ대한통운") / 못 찾으면 ("", "")
    """
    if not bid_numeric:
        return "", ""
    hook = """
      (() => {
        if (window.__kmHooked) return;
        window.__kmHooked = true;
        const of = window.fetch;
        window.fetch = function (input, init) {
          const url = (typeof input === 'string') ? input : (input && input.url) || '';
          return of.apply(this, arguments).then(res => {
            if (url.indexOf('/api/m/bids/') !== -1) {
              res.clone().json().then(j => { window.__kmBid = j; }).catch(() => {});
            }
            return res;
          });
        };
      })()
    """
    conn.call("Page.addScriptToEvaluateOnNewDocument", {"source": hook})
    conn.send("Page.navigate", {"url": f"https://kream.co.kr/my/buying/{bid_numeric}"})
    for wait in (2.5, 2.0, 2.0):
        time.sleep(wait)
        r = conn.call(
            "Runtime.evaluate",
            {
                "expression": "JSON.stringify((window.__kmBid||{}).tracking||null)",
                "returnByValue": True,
            },
        )
        v = (r.get("result", {}).get("result", {}) or {}).get("value")
        if v and v != "null":
            try:
                t = json.loads(v)
            except Exception:
                continue
            return (
                str(t.get("tracking_code") or ""),
                str((t.get("logistics_company") or {}).get("name") or ""),
            )
    return "", ""


MIN_EXPECTED_ORDERS = (
    20  # 이보다 적게 읽히면 크림 탭/스크롤이 제대로 안 된 걸로 보고 중단(K:N 보호)
)

# 자동매칭 대상 최소 날짜 — 이보다 오래된 크림 배송완료건은 이 시트 추적범위(8/8~) 밖이라
# 이미 다른 경로로 처리됐을 가능성이 높음(2026-08-13 7월건 오매칭 사고). 자동매칭 제외,
# 사람이 직접 확인해야 함.
AUTO_MATCH_MIN_DATE = "26/08/01"


def fetch_new_ebay_orders():
    """DB에서 미발송(발주확인) 잉어킹 이베이 주문 목록 — docker exec로 조회."""
    import subprocess

    query_script = r"""
import asyncio, asyncpg, json, datetime
async def main():
    conn = await asyncpg.connect(host='postgres', port=5432, user='samba',
        password='09aac90f3fb8c4394ad2d6062b1a5910', database='samba', ssl=False)
    rows = await conn.fetch('''
        SELECT order_number, quantity, created_at, ship_by_at, product_name
        FROM samba_order
        WHERE source='ebay' AND product_name ILIKE '%Magikarp%'
          AND status NOT IN ('cancelled','cancel_requested','refunded','returned')
          AND status != 'shipping'
        ORDER BY created_at ASC
    ''')
    kst = datetime.timezone(datetime.timedelta(hours=9))
    out = []
    for r in rows:
        # 이베이가 shipByDate 아직 안 준 신규주문 — created_at+7일로 대체(다른 주문들 실측 패턴)
        ship_by = r["ship_by_at"] or (r["created_at"] + datetime.timedelta(days=7))
        # 상품명에 "Card Ver" 가 있으면 카드버전 — 크림 쪽과 같은 규칙.
        #   Pokemon TCG Mega Festa 2026 Promo Card Magikarp (Card Ver)  ← 카드
        #   Pokemon Card Magikarp Promo (Korean)                        ← 팩(밀봉)
        _cv = "card ver" in str(r["product_name"] or "").lower()
        out.append({"order_number": r["order_number"], "quantity": r["quantity"],
                     "card_ver": _cv,
                     "ship_by_at": ship_by.strftime("%Y. %-m. %-d"),
                     "order_date": r["created_at"].astimezone(kst).strftime("%Y. %-m. %-d")})
    print(json.dumps(out, ensure_ascii=False))
asyncio.run(main())
"""
    tmp_local = "C:/tmp/_ebay_orders_query.py"
    with open(tmp_local, "w", encoding="utf-8") as f:
        f.write(query_script)
    # [2026-08-18] pythonw 로 띄워도 docker 를 부를 때마다 콘솔 창이 깜빡였다.
    # 작업스케줄러가 1분마다 도는 스크립트라 창이 계속 떠서 CREATE_NO_WINDOW 로 막는다.
    _no_win = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    subprocess.run(
        ["docker", "cp", tmp_local, "local-samba-api-1:/tmp/_ebay_orders_query.py"],
        check=True,
        **_no_win,
    )
    result = subprocess.run(
        [
            "docker",
            "exec",
            "local-samba-api-1",
            "/app/backend/.venv/bin/python",
            "/tmp/_ebay_orders_query.py",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        **_no_win,
    )
    return json.loads(result.stdout.strip())


def _paint_ebay_card_ver(ws, db_orders):
    """이베이 주문번호(B열) 중 카드버전만 빨간 글씨로 — 크림(L열)과 같은 표시.

    판별은 상품명의 "Card Ver" 다.
      Pokemon TCG Mega Festa 2026 Promo Card Magikarp (Card Ver)  ← 카드
      Pokemon Card Magikarp Promo (Korean)                        ← 팩(밀봉)
    신규 행만 칠하면 이미 시트에 있던 주문이 빠지므로 B열 전체를 훑어 칠한다.
    같은 주문번호가 수량만큼 여러 행에 걸쳐 있어 행 단위로 맞춘다.
    """
    cards = {o["order_number"] for o in db_orders if o.get("card_ver")}
    if not cards:
        return
    try:
        b_col = ws.col_values(2)
        rows = [i for i, v in enumerate(b_col, 1) if v.strip() in cards]
        for row in rows:
            ws.format(f"B{row}", {"textFormat": {"foregroundColor": RED}})
        if rows:
            print(f"    이베이 카드버전 {len(rows)}행 빨간색 표시")
    except Exception as e:
        print(f"    [경고] 이베이 카드버전 색상 표시 실패(건너뜀): {e}")


def append_new_ebay_orders(ws):
    """DB에 있는데 시트 B열에 없는 이베이 주문 -> 맨 아래 수량만큼 행 추가."""
    existing_b = {v for v in ws.col_values(2) if v.strip()}
    db_orders = fetch_new_ebay_orders()
    new_orders = [o for o in db_orders if o["order_number"] not in existing_b]
    if not new_orders:
        print("[0] 신규 이베이 주문 없음")
        _paint_ebay_card_ver(ws, db_orders)
        return
    a_col = ws.col_values(1)
    last_row = len(a_col)
    rows = []
    card_rows = []  # 카드버전 행 번호 — 주문번호를 빨갛게 칠한다
    for o in new_orders:
        for seq in range(1, o["quantity"] + 1):
            if o.get("card_ver"):
                card_rows.append(last_row + 1 + len(rows))
            rows.append(
                [
                    o["order_date"],
                    o["order_number"],
                    str(seq),
                    "",
                    "",
                    "97.30%",
                    "0",
                    "",
                    o["ship_by_at"],
                ]
            )
    ws.update(
        range_name=f"A{last_row + 1}", values=rows, value_input_option="USER_ENTERED"
    )
    _paint_ebay_card_ver(ws, db_orders)
    print(
        f"[0] 신규 이베이 주문 {len(new_orders)}건({len(rows)}행) 추가: "
        f"{', '.join(o['order_number'] for o in new_orders)}"
    )


def match_delivered_to_ai(ws, newly_delivered):
    """배송완료건을 A:I 빈 슬롯(D열 공백)에 도착순으로 채움. D열에 값 있는 행은 무조건 건너뜀."""
    eligible = [
        (no, info)
        for no, info in newly_delivered
        if info["date"] >= AUTO_MATCH_MIN_DATE
    ]
    skipped_old = len(newly_delivered) - len(eligible)
    if skipped_old:
        print(
            f"    [주의] {skipped_old}건은 {AUTO_MATCH_MIN_DATE} 이전 주문이라 자동매칭 제외(수동확인 필요)"
        )
    if not eligible:
        return

    ai = ws.get("A2:I1000")
    empty_slots = []
    for i, r in enumerate(ai):
        row = i + 2
        b = r[1] if len(r) > 1 else ""
        d = r[3] if len(r) > 3 else ""
        if b.strip() and not d.strip():
            empty_slots.append(row)

    if not empty_slots:
        print("    빈 슬롯 없음 — 매칭 건너뜀")
        return

    eligible.sort(key=lambda x: x[1]["date"])
    # 번장 건은 가격이 이미 들어 있어 크림 탭이 없어도 처리할 수 있다.
    need_kream = any(not _is_bunjang(no) for no, _ in eligible)
    price_tab = find_kream_tab("kream.co.kr/my/buying")
    price_conn = CDPConn(price_tab) if price_tab else None
    if need_kream and not price_conn:
        print("    가격조회용 탭 없음 — 매칭 건너뜀")
        return
    if price_conn:
        price_conn.call("Page.enable")
        price_conn.call("Runtime.enable")

    n = min(len(eligible), len(empty_slots))
    updates = []
    for i in range(n):
        order_no, info = eligible[i]
        row = empty_slots[i]
        if order_no.startswith("O-OR"):
            price, _bid = fetch_price(price_conn, order_no.replace("O-OR", ""))
        else:
            price = info.get("price") or ""  # 번장 — 총 결제금액 이미 확보
        _now = time.localtime()
        today = f"{_now.tm_year}. {_now.tm_mon}. {_now.tm_mday}"
        updates.append({"range": f"D{row}:E{row}", "values": [[order_no, price or ""]]})
        updates.append({"range": f"H{row}", "values": [[today]]})
        print(f"    row{row} <- {order_no} ({price})")
    if price_conn:
        price_conn.close()
    ws.batch_update(updates, value_input_option="USER_ENTERED")
    print(f"[3] A:I 매칭 {n}건 완료 (빈슬롯 {len(empty_slots)}개 중)")


def _paint_card_ver(ws, card_flags):
    """K:N 의 주문번호(L열) 중 카드버전만 빨간 글씨로 칠한다.

    크림 옵션이 "Ungraded A (Card Ver.)" 인 건이 대상. 시트를 매번 새로 쓰므로
    먼저 전체를 검정으로 되돌린 뒤 해당 행만 빨갛게 한다(안 그러면 이전 실행의
    빨간색이 엉뚱한 행에 남는다). card_flags 는 실제 기록된 행과 같은 순서다.
    """
    if not card_flags:
        return
    ws.format(f"L2:L{len(card_flags) + 1}", {"textFormat": {"foregroundColor": BLACK}})
    reds = [i + 2 for i, is_card in enumerate(card_flags) if is_card]
    for row in reds:
        ws.format(f"L{row}", {"textFormat": {"foregroundColor": RED}})
    print(f"    카드버전 {len(reds)}건 빨간색 표시")


def main():
    gc = gspread.service_account(filename=CREDS_PATH)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB_NAME)

    print("[0] 이베이 신규주문 확인...")
    try:
        append_new_ebay_orders(ws)
    except Exception as e:
        print(f"    [경고] 이베이 신규주문 조회 실패(건너뜀): {e}")

    print("[1] 크림 주문 읽는 중...")
    orders = fetch_kream_orders()
    print(f"    총 {len(orders)}건")

    if len(orders) < MIN_EXPECTED_ORDERS:
        print(
            f"    [경고] {MIN_EXPECTED_ORDERS}건 미만 — 크림 탭을 못 읽은 것으로 판단, "
            f"K:N 안 건드리고 중단"
        )
        return

    # A:I 에 이미 매칭 확정된 크림주문번호 (D열) — 여기 있는 건 신규 배송완료로 다시 잡으면 안 됨
    ai_kream_orders = {v for v in ws.col_values(4) if v.startswith("O-OR")}

    # 배송완료 판정 — 크림 상태에 "배송완료" 텍스트가 오는 경우는 buying list 자체에선
    # "발송완료"(판매자->크림) 다음 최종 도착 시 "배송완료"로 바뀜. finished 탭 상태값을 그대로 사용.
    newly_delivered = []
    still_pending = []
    for order_no, info in orders.items():
        status = info["status"]
        if order_no in ai_kream_orders:
            continue  # 이미 이베이 테이블에 매칭 완료된 건 — 재처리 금지
        if status in ("배송완료",):
            newly_delivered.append((order_no, info))
        elif status == "취소완료":
            continue  # 취소된건 무시
        else:
            still_pending.append((order_no, info))

    # ── 번개장터 구매건 [2026-08-18] ──
    # 크림과 같은 규칙: 구매확정(=배송완료)된 건은 A:I 로 넘기고, 나머지는 K:N 에 섞는다.
    # 번장은 API 로 받으므로 가격(총 결제금액)이 이미 들어 있어 상세 재조회가 필요 없다.
    bj_orders = {}
    try:
        bj_orders = bj.fetch_bunjang_orders()
        print(f"[1-2] 번장 주문 {len(bj_orders)}건")
    except Exception as e:
        print(f"    [경고] 번장 조회 실패(건너뜀): {e}")

    ai_bj_orders = {v for v in ws.col_values(4) if v.isdigit()}
    for oid, info in bj_orders.items():
        if oid in ai_bj_orders:
            continue  # 이미 이베이 표에 매칭 완료
        if info["done"]:
            newly_delivered.append((oid, info))
        else:
            still_pending.append((oid, info))

    print(
        f"[2] 신규 배송완료 {len(newly_delivered)}건, 미배송 {len(still_pending)}건 "
        f"(A:I 기존 매칭 크림 {len(ai_kream_orders)} · 번장 {len(ai_bj_orders)}건 제외)"
    )

    if newly_delivered:
        print("[3] A:I 빈 슬롯에 매칭 중...")
        try:
            match_delivered_to_ai(ws, newly_delivered)
        except Exception as e:
            print(f"    [경고] A:I 매칭 실패(건너뜀): {e}")

    price_tab = find_kream_tab("kream.co.kr/my/buying")
    price_conn = CDPConn(price_tab) if price_tab else None
    if price_conn:
        price_conn.call("Page.enable")
        price_conn.call("Runtime.enable")

    # K:N 전체 새로 작성 (가격 포함)
    print("[4] K:N 섹션 재작성 (가격 포함)...")
    still_pending.sort(key=lambda x: _sort_key(x[0], x[1]["status"]))
    kn_rows = []
    kn_card_ver = []  # kn_rows 와 같은 순서 — 중간에 건너뛴 건이 있어도 안 어긋나게
    for order_no, info in still_pending:
        d = info["date"].split(" ")[0]  # 26/08/13
        if not d:
            continue
        y, m, dd = d.split("/")
        kdate = f"20{y}. {int(m)}. {int(dd)}"
        # 배송 중인 건은 N열(배송상황)에 "배송 중" 대신 송장번호를 적는다.
        # 그 전 단계는 아직 송장이 없으니 상태 문자열을 그대로 둔다.
        invoice = ""
        if order_no.startswith("O-OR"):
            # 크림은 상세 페이지에서 결제금액을 읽어야 한다
            if not price_conn:
                continue
            price, bid_no = fetch_price(price_conn, order_no.replace("O-OR", ""))
            if info["status"] == "배송 중":
                invoice, _company = fetch_tracking(price_conn, bid_no)
        else:
            price = info.get("price") or ""  # 번장 — 총 결제금액 이미 확보
            if info["status"] == bj.ST_IN_TRANSIT:
                invoice = info.get("invoice") or ""
        # [2026-08-20] 송장번호는 **문자열로 넣는다.** USER_ENTERED 로 쓰면 구글시트가
        # 순수 숫자 송장(92889408614)을 숫자로 해석해 천 단위 콤마를 찍는다
        # (실측: "92,889,408,614" · 번장 "460,444,071,684"). 앞에 작은따옴표를 붙이면
        # 시트가 텍스트로 강제하고 화면에는 따옴표가 보이지 않는다.
        _n = invoice or info["status"]
        if invoice and str(invoice).replace("-", "").isdigit():
            _n = "'" + str(invoice)
        kn_rows.append([kdate, order_no, price or "", _n])
        kn_card_ver.append(bool(info.get("card_ver")))
        print(f"    {order_no}: {price}{' / 송장 ' + invoice if invoice else ''}")

    if price_conn:
        price_conn.close()

    ws.batch_clear(["K2:N1000"])
    if kn_rows:
        ws.update(range_name="K2", values=kn_rows, value_input_option="USER_ENTERED")
    print(f"    {len(kn_rows)}행 반영")

    # 카드버전(옵션에 "Card Ver.")은 주문번호를 빨간 글씨로 — 한눈에 구분하려고.
    # 매번 K:N 을 통째로 다시 쓰므로 색도 매번 새로 칠한다(먼저 전부 검정으로 되돌린다).
    try:
        _paint_card_ver(ws, kn_card_ver)
    except Exception as e:
        print(f"    [경고] 카드버전 색상 표시 실패(건너뜀): {e}")

    print("DONE")


if __name__ == "__main__":
    main()
