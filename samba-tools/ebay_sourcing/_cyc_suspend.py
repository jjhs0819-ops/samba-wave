"""no_match.json(대체매물 없음/비카드) 14건 -> 판매중지(availableQuantity=0) [컨테이너].

삭제 아님. offer PUBLISHED 유지, 주문가능수량만 0 (project rule: 삭제≠판매중지).
price_locked는 사전 확인(0건)이라 스킵 로직 없음 — 재확인 안전장치로 남겨둠.
"""
import asyncio
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

import httpx  # noqa: E402

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"


async def suspend_one(ec, s, sku):
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from sqlmodel import select

    p = (
        (await s.execute(select(SambaCollectedProduct).where(SambaCollectedProduct.id == sku)))
        .scalars()
        .first()
    )
    if p and p.price_locked:
        return "SKIP(고정가)"

    tk = await ec._get_access_token()
    h = {
        "Authorization": f"Bearer {tk}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Content-Language": "en-US",
    }
    async with httpx.AsyncClient(timeout=60) as c:
        ro = await c.get(f"{ec._base_url}/sell/inventory/v1/offer?sku={sku}", headers=h)
        offers = ro.json().get("offers", []) if ro.status_code == 200 else []
        if not offers:
            return "offer없음"
        results = []
        for o in offers:
            payload = {
                "sku": sku,
                "marketplaceId": o.get("marketplaceId", "EBAY_US"),
                "format": o.get("format", "FIXED_PRICE"),
                "availableQuantity": 0,
                "categoryId": o.get("categoryId"),
                "listingDescription": o.get("listingDescription"),
                "listingPolicies": o.get("listingPolicies"),
                "pricingSummary": o.get("pricingSummary"),
                "merchantLocationKey": o.get("merchantLocationKey"),
                "quantityLimitPerBuyer": o.get("quantityLimitPerBuyer"),
            }
            payload = {k: v for k, v in payload.items() if v is not None}
            r2 = await c.put(
                f"{ec._base_url}/sell/inventory/v1/offer/{o['offerId']}", headers=h, json=payload
            )
            results.append(r2.status_code)
            if o.get("status") == "PUBLISHED":
                await c.post(f"{ec._base_url}/sell/inventory/v1/offer/{o['offerId']}/publish", headers=h)

    if p:
        d = dict(p.stock_quantities or {})
        d[KV] = 0
        p.stock_quantities = d
        p.sale_status = "sold_out"
        s.add(p)
        await s.commit()
    return f"OK {results}"


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlmodel import select

    with open("/tmp/no_match.json", "r", encoding="utf-8") as f:
        items = json.load(f)

    tok = current_tenant_id.set(TENANT)
    ok = fail = 0
    try:
        async with get_write_session() as s0:
            acc = (
                (await s0.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV)))
                .scalars()
                .first()
            )
            addf = acc.additional_fields or {}
        ec = EbayClient(
            app_id=addf.get("clientId") or acc.api_key,
            dev_id=addf.get("devId", ""),
            cert_id=addf.get("clientSecret") or acc.api_secret,
            refresh_token=addf.get("oauthToken") or acc.oauth_refresh_token,
        )
        for it in items:
            sku = it["id"]
            try:
                async with get_write_session() as s:
                    res = await suspend_one(ec, s, sku)
                print(f"[{sku}] {it['name'][:24]} -> {res}")
                if res.startswith("OK"):
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                print(f"[{sku}] ERR {e}")
                fail += 1
    finally:
        current_tenant_id.reset(tok)
    print(f"\n=== 판매중지 완료 {ok} / 스킵·실패 {fail} ===")


if __name__ == "__main__":
    asyncio.run(main())
