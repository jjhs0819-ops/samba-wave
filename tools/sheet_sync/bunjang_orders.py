# -*- coding: utf-8 -*-
"""번개장터 구매내역 수집 — 크림매칭 시트용.

크림은 로그인 페이지를 CDP 로 긁지만, 번장은 API 가 열려 있어 그걸 쓴다.
화면 스크롤보다 훨씬 빠르고 안 깨진다.

  목록  GET /api/order/v2/history/purchase-orders
        ?page=&size=&filter.status={on_progress|completed}&filter.type=all
  상세  GET /api/order/v2/bun-pay-orders/buyer/{orderId}
        payment.amount = 총 결제금액   ← 시트에 넣을 값

**목록의 price 는 상품금액이라 배송비가 빠진다**(실측 75,000 vs 총결제 77,000).
크림과 마찬가지로 상세의 총 결제금액을 써야 한다.

인증은 X-BUN-AUTH-TOKEN 헤더. localStorage 에 없어서 웨일 탭이 실제로 보내는
헤더를 CDP 로 가로챈다.

상태값(실측): in_transit / ship_ready / payment_received / purchase_confirm.
화면에서 "배송 준비 중"과 "상품 준비 중"으로 갈려 보이지만 API 값은 ship_ready
하나이고, hasReservedDeliveryService 로 갈린다.
"""

import json
import time
import urllib.request

from cdp_sheet_helpers import CDPConn

CDP_HOST, CDP_PORT = "localhost", 9223
API = "https://api.bunjang.co.kr"
ORDER_URL = "https://order.bunjang.co.kr/?isPageHeader=true"

# 시트 표기 — 출처 꼬리표를 붙이지 않는다(주문번호 형태로 이미 구분된다).
# 크림과 겹치는 값은 "배송 중" 뿐이고, 정렬은 kream_ebay_sync 가 주문번호로
# 크림/번장을 갈라 순위를 매긴다.
ST_IN_TRANSIT = "배송 중"
ST_SHIP_READY = "배송준비중"
ST_ITEM_READY = "상품준비중"
ST_PAID = "결제완료"
ST_DELIVERED = "배송완료"  # delivery_completed — 구매확정 직전 단계
ST_DONE = "구매확정"


def _tabs():
    resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=10)
    return json.loads(resp.read())


def _open_tab(url):
    req = urllib.request.Request(
        f"http://{CDP_HOST}:{CDP_PORT}/json/new?{url}", method="PUT"
    )
    urllib.request.urlopen(req, timeout=10)


def _new_tab():
    """작업 전용 탭을 새로 연다.

    기존 번장 탭을 재사용하면 사람이 보던 탭을 가로채고, 오래된 탭은 CDP 응답이
    아예 안 오는 경우가 있다(2026-08-18 실측: Page.enable 에서 타임아웃).
    매번 새로 열고 끝나면 닫는 편이 확실하다.
    """
    before = {t["id"] for t in _tabs()}
    _open_tab(ORDER_URL)
    for _ in range(10):
        time.sleep(1)
        for t in _tabs():
            if (
                t.get("type") == "page"
                and t["id"] not in before
                and "bunjang" in (t.get("url") or "")
            ):
                return t["id"]
    return None


def _close_tab(tab_id):
    try:
        urllib.request.urlopen(
            f"http://{CDP_HOST}:{CDP_PORT}/json/close/{tab_id}", timeout=5
        )
    except Exception:
        pass


def _grab_token(conn):
    """페이지가 실제로 보내는 X-BUN-AUTH-TOKEN 을 가로챈다.

    토큰이 localStorage/쿠키에 없어서 요청 헤더를 보는 수밖에 없다.
    페이지를 다시 열면 목록 API 를 부르므로 그때 잡는다.
    """
    # CDPConn 은 요청/응답 짝만 다루고 이벤트 수신기가 없어서 Network 이벤트를
    # 직접 읽으면 응답 대기와 엉킨다. 대신 페이지 로드 전에 fetch/XHR 을 감싸는
    # 후킹을 심어두고, 앱이 스스로 API 를 부를 때 토큰을 변수에 남기게 한다.
    hook = """
      (() => {
        if (window.__bunHooked) return;
        window.__bunHooked = true;
        const pick = (h) => {
          try {
            if (!h) return;
            if (typeof h.get === 'function') {
              const v = h.get('X-BUN-AUTH-TOKEN') || h.get('x-bun-auth-token');
              if (v) window.__bunToken = v;
              return;
            }
            for (const k in h) {
              if (k.toLowerCase() === 'x-bun-auth-token' && h[k]) window.__bunToken = h[k];
            }
          } catch (e) {}
        };
        const of = window.fetch;
        window.fetch = function (input, init) {
          if (init && init.headers) pick(init.headers);
          if (input && input.headers) pick(input.headers);
          return of.apply(this, arguments);
        };
        const os = XMLHttpRequest.prototype.setRequestHeader;
        XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
          if (String(k).toLowerCase() === 'x-bun-auth-token' && v) window.__bunToken = v;
          return os.apply(this, arguments);
        };
      })()
    """
    conn.call("Page.addScriptToEvaluateOnNewDocument", {"source": hook})
    conn.send("Page.navigate", {"url": ORDER_URL})

    deadline = time.time() + 30
    while time.time() < deadline:
        time.sleep(2)
        r = conn.call(
            "Runtime.evaluate",
            {"expression": "window.__bunToken || ''", "returnByValue": True},
        )
        v = r.get("result", {}).get("result", {}).get("value")
        if v:
            return v
    return None


def _fetch(conn, token, path):
    """웨일 탭 안에서 fetch — 크로스오리진·세션 문제를 피한다."""
    expr = """(async () => {
      const r = await fetch(%s, {headers: {'X-BUN-AUTH-TOKEN': %s,
                                            'Accept': 'application/json'}});
      return JSON.stringify({status: r.status, body: await r.text()});
    })()""" % (json.dumps(API + path), json.dumps(token))
    r = conn.call(
        "Runtime.evaluate",
        {"expression": expr, "awaitPromise": True, "returnByValue": True},
    )
    v = r.get("result", {}).get("result", {}).get("value")
    if not v:
        return None
    d = json.loads(v)
    if d["status"] != 200:
        return None
    return json.loads(d["body"])


# 번장 orderStatus → 시트 표기 [2026-08-23]
# 매핑에 없는 값을 그대로 흘려보내 `delivery_completed` 가 영문 그대로 시트에
# 박혔다. 아는 값은 전부 여기 적고, 모르는 값이 오면 눈에 띄게 표시한다.
_STATUS_MAP = {
    "in_transit": ST_IN_TRANSIT,
    "payment_received": ST_PAID,
    "delivery_completed": ST_DELIVERED,
    "purchase_confirm": ST_DONE,
}

# 배송이 끝난 상태 — 이베이 주문건에 매칭할 대상이다(K:N 대기열에 남기지 않는다).
DELIVERED_STATUSES = ("delivery_completed", "purchase_confirm")


def _sheet_status(order_status, has_reserved):
    if order_status == "ship_ready":
        # 화면 문구가 갈리는 기준 — 배송예약이 잡혀 있으면 '배송 준비 중'
        return ST_SHIP_READY if has_reserved else ST_ITEM_READY
    hit = _STATUS_MAP.get(order_status)
    if hit:
        return hit
    # 모르는 상태 — 영문을 그대로 두면 시트에서 원인을 못 찾는다.
    print(f"    [경고] 번장 orderStatus 미매핑: {order_status}")
    return f"미매핑({order_status})"


def fetch_bunjang_orders(max_pages=40):
    """번장 구매내역 전체.

    반환: {order_id(str): {"date": "26/08/18 07:58", "status": 시트표기,
                            "price": "77,000", "done": bool}}
    """
    tab = _new_tab()
    if not tab:
        raise RuntimeError("번장 탭을 못 열었다 — 웨일 CDP 확인 필요")

    conn = CDPConn(tab)
    try:
        conn.call("Page.enable")
        conn.call("Runtime.enable")
        token = _grab_token(conn)
    except Exception:
        conn.close()
        _close_tab(tab)
        raise
    if not token:
        conn.close()
        _close_tab(tab)
        raise RuntimeError("번장 인증 토큰을 못 잡았다 — 로그인 상태 확인 필요")

    out = {}
    for st in ("on_progress", "completed"):
        for page in range(max_pages):
            j = _fetch(
                conn,
                token,
                f"/api/order/v2/history/purchase-orders?page={page}&size=50"
                f"&filter.status={st}&filter.type=all",
            )
            if not j:
                break
            for o in j.get("data") or []:
                oid = str(o.get("orderId") or "")
                items = o.get("orderItems") or []
                if not oid or not items:
                    continue
                it = items[0]
                name = str(it.get("productName") or "")
                # 크림 쪽과 같은 기준으로 대상 상품만
                if "잉어킹" not in name and "Magikarp" not in name.lower():
                    continue
                created = str(o.get("createdAt") or "")  # 2026-08-18T07:58:41+09:00
                date = ""
                if len(created) >= 16:
                    date = f"{created[2:4]}/{created[5:7]}/{created[8:10]} {created[11:16]}"
                out[oid] = {
                    "date": date,
                    "status": _sheet_status(
                        it.get("orderStatus"), bool(o.get("hasReservedDeliveryService"))
                    ),
                    "price": "",
                    "invoice": "",  # 배송 중이면 상세에서 채운다
                    # [2026-08-23] 배송완료도 '끝난 건'이다. 종전엔 purchase_confirm
                    # 만 봐서, 배송이 끝났는데 구매확정 전인 주문이 이베이 매칭으로
                    # 넘어가지 못하고 K:N 대기열에 계속 남았다.
                    "done": it.get("orderStatus") in DELIVERED_STATUSES,
                }
            if not j.get("hasNext"):
                break

    # 총 결제금액과 송장번호는 상세에만 있다
    for oid, info in out.items():
        d = _fetch(conn, token, f"/api/order/v2/bun-pay-orders/buyer/{oid}")
        data = (d or {}).get("data") or {}
        amount = (data.get("payment") or {}).get("amount")
        if amount:
            info["price"] = f"{int(amount):,}"
        inv = ((data.get("delivery") or {}).get("invoice") or {}).get("invoiceNo")
        if inv:
            info["invoice"] = str(inv)

    conn.close()
    _close_tab(tab)
    return out
