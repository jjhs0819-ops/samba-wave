"""네고/제시가 매물 오판 수정: 소스는 그대로 두고 원가만 시세로 교정 [컨테이너, 수수료0]."""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
TARGET = "cp_01KYY9SA58GCE55WRVVG2Q1DA1"
REAL_COST = 400000.0  # 동일카드(비네고) 시세 중앙값 근사


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.ebay import EbayClient
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlmodel import select

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            acc = (
                (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV)))
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
            offs = await ec.get_offers_by_sku(TARGET)
            before = offs[0].get("listing", {}).get("listingId") if offs else None
            cat = offs[0].get("categoryId", "183454") if offs else "183454"

            p = (
                (await s.execute(select(SambaCollectedProduct).where(SambaCollectedProduct.id == TARGET)))
                .scalars()
                .first()
            )
            print("수정전 cost:", p.cost, "source:", p.source_url)
            # 소스/이미지 그대로, 원가만 교정
            p.cost = REAL_COST
            p.sale_price = REAL_COST
            p.original_price = REAL_COST
            p.sale_status = "in_stock"
            d = dict(p.stock_quantities or {})
            d[KV] = 1
            p.stock_quantities = d
            s.add(p)
            await s.flush()

            res = await dispatch_to_market(
                s, "ebay", p.model_dump(), category_id=cat, account=acc, existing_product_no=before
            )
            await s.commit()
            print("dispatch:", res.get("success"), res.get("message", "")[:100])

            offs2 = await ec.get_offers_by_sku(TARGET)
            after = offs2[0]
            print(
                "after price:", after.get("pricingSummary", {}).get("price", {}),
                "qty:", after.get("availableQuantity"),
                "status:", after.get("status"),
            )
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
