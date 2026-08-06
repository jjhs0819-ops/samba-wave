"""함정매물(제시가/교환가) 긴급 판매중지 [컨테이너]. availableQuantity=0, 삭제 아님."""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

import httpx  # noqa: E402

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
TARGETS = ["cp_01KYXWJTYVJ4S6JSY2VV2C6746", "cp_01KYY8VS1WP0Y42EQVE154D289"]


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlmodel import select

    tok = current_tenant_id.set(TENANT)
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
        tk = await ec._get_access_token()
        h = {
            "Authorization": f"Bearer {tk}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Content-Language": "en-US",
        }
        async with httpx.AsyncClient(timeout=60) as c:
            for sku in TARGETS:
                ro = await c.get(f"{ec._base_url}/sell/inventory/v1/offer?sku={sku}", headers=h)
                offers = ro.json().get("offers", []) if ro.status_code == 200 else []
                if not offers:
                    print(f"[{sku}] offer 없음")
                    continue
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
                    r2 = await c.put(f"{ec._base_url}/sell/inventory/v1/offer/{o['offerId']}", headers=h, json=payload)
                    print(f"[{sku}] 판매중지 {r2.status_code}")
                async with get_write_session() as s:
                    p = (
                        (await s.execute(select(SambaCollectedProduct).where(SambaCollectedProduct.id == sku)))
                        .scalars()
                        .first()
                    )
                    d = dict(p.stock_quantities or {})
                    d[KV] = 0
                    p.stock_quantities = d
                    p.sale_status = "sold_out"
                    s.add(p)
                    await s.commit()
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
