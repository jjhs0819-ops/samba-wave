"""리스팅 판매가능 재고 맞추기 [컨테이너 실행].

함정: eBay 는 취소·환불해도 soldQuantity 를 되돌리지 않는다.
inventory_item 수량에서 이미 팔린 수량만큼 빠진 값이 실제 주문가능 수량이라
"10개 팔고 싶으면 (10 + 이미팔린수)" 를 넣어야 한다.
(2026-07-23 응원봉: 수량 3 − 판매 3 = 0 → 계속 품절 표시)

DB stock_quantities 도 같이 맞춰, 다음 전송 때 되돌아가지 않게 한다.

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 \
      /tmp/set_stock.py <SKU> <판매가능수량>
"""

import asyncio
import io
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"  # k-tcg_vault 전용


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.resolver import resolve_market_creds
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlmodel import select

    sku, want = sys.argv[1], int(sys.argv[2])
    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            acc = (await s.execute(
                select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()
            ax = getattr(acc, "additional_fields", None) or {}
            cr = await resolve_market_creds(s, TENANT, market_type="ebay", store_key="store_ebay") or {}
            ec = EbayClient(
                cr.get("clientId") or cr.get("appId") or ax.get("clientId") or ax.get("appId", ""),
                cr.get("devId") or ax.get("devId", ""),
                cr.get("clientSecret") or cr.get("certId") or ax.get("clientSecret") or ax.get("certId", ""),
                cr.get("oauthToken") or cr.get("authToken") or ax.get("oauthToken") or ax.get("authToken", ""))
            tk = await ec._get_access_token()
            h = {"Authorization": f"Bearer {tk}", "Accept": "application/json",
                 "Content-Type": "application/json", "Content-Language": "en-US"}

            async with httpx.AsyncClient(timeout=60) as c:
                ri = await c.get(f"{ec._base_url}/sell/inventory/v1/inventory_item/{sku}", headers=h)
                if ri.status_code != 200:
                    print(f"inventory_item 조회 실패 {ri.status_code} {ri.text[:150]}")
                    return
                item = ri.json()
                ro = await c.get(f"{ec._base_url}/sell/inventory/v1/offer?sku={sku}", headers=h)
                offers = ro.json().get("offers", []) if ro.status_code == 200 else []
                sold = max((int((o.get("listing") or {}).get("soldQuantity", 0) or 0)) for o in offers) if offers else 0
                cur = ((item.get("availability") or {}).get("shipToLocationAvailability") or {}).get("quantity", 0)
                target = want + sold
                print(f"현재 수량 {cur} | 판매됨 {sold} | 주문가능 {max(0, cur - sold)}")
                print(f"→ 목표 판매가능 {want} 이므로 수량을 {target} 로 설정")

                item.setdefault("availability", {}).setdefault(
                    "shipToLocationAvailability", {})["quantity"] = target
                item.pop("sku", None)
                ru = await c.put(f"{ec._base_url}/sell/inventory/v1/inventory_item/{sku}",
                                 headers=h, json=item)
                print(f"  inventory_item 수정 {ru.status_code}"
                      + ("" if ru.status_code < 400 else f" {ru.text[:200]}"))
                if ru.status_code >= 400:
                    return
                # [중요] offer 에도 availableQuantity 가 따로 있다. item 수량만 고치면
                # 주문가능 수량이 0 그대로라 품절 표시가 안 풀린다(2026-07-23).
                for o in offers:
                    payload = {
                        "sku": sku,
                        "marketplaceId": o.get("marketplaceId", "EBAY_US"),
                        "format": o.get("format", "FIXED_PRICE"),
                        "availableQuantity": want,
                        "categoryId": o.get("categoryId"),
                        "listingDescription": o.get("listingDescription"),
                        "listingPolicies": o.get("listingPolicies"),
                        "pricingSummary": o.get("pricingSummary"),
                        "merchantLocationKey": o.get("merchantLocationKey"),
                        "quantityLimitPerBuyer": o.get("quantityLimitPerBuyer"),
                    }
                    payload = {k: v for k, v in payload.items() if v is not None}
                    ro2 = await c.put(f"{ec._base_url}/sell/inventory/v1/offer/{o['offerId']}",
                                      headers=h, json=payload)
                    print(f"  offer 수량 {want} → {ro2.status_code}"
                          + ("" if ro2.status_code < 400 else f" {ro2.text[:200]}"))
                    if o.get("status") == "PUBLISHED":
                        pr = await c.post(
                            f"{ec._base_url}/sell/inventory/v1/offer/{o['offerId']}/publish", headers=h)
                        print(f"  재게시 {pr.status_code}")

                p = (await s.execute(select(SambaCollectedProduct).where(
                    SambaCollectedProduct.id == sku))).scalars().first()
                if p:
                    d = dict(p.stock_quantities or {})
                    d[KV] = target
                    p.stock_quantities = d
                    p.sale_status = "in_stock"
                    s.add(p)
                    await s.commit()
                    print(f"  DB stock_quantities → {target}")

                rc = await c.get(f"{ec._base_url}/sell/inventory/v1/offer?sku={sku}", headers=h)
                for o in (rc.json().get("offers", []) if rc.status_code == 200 else []):
                    print(f"  확인: 주문가능 {o.get('availableQuantity')} / 상태 {o.get('status')}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
