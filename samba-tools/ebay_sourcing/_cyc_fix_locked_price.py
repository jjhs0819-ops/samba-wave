"""고정가 드리프트 수정: locked_prices 값으로 재dispatch [컨테이너, 수수료0].

price_locked=true면 ebay.py가 cost 무시하고 locked_prices[acc]를 그대로 쓰므로
현재 DB값 안 건드리고 재전송만 하면 라이브가 잠금가로 맞춰진다.
"""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
TARGET = "cp_01KY67WWT5GHYR6Z4A44PBAFTP"


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
            if not offs:
                print("offer 없음")
                return
            before = offs[0].get("listing", {}).get("listingId")
            cat = offs[0].get("categoryId", "")

            p = (
                (await s.execute(select(SambaCollectedProduct).where(SambaCollectedProduct.id == TARGET)))
                .scalars()
                .first()
            )
            res = await dispatch_to_market(
                s, "ebay", p.model_dump(), category_id=cat, account=acc, existing_product_no=before
            )
            await s.commit()
            print("dispatch:", res.get("success"), res.get("message", "")[:100])

            offs2 = await ec.get_offers_by_sku(TARGET)
            after = offs2[0]
            print(
                "after listingId:", after.get("listing", {}).get("listingId"),
                "price:", after.get("pricingSummary", {}).get("price", {}),
                "(before:", before, ")",
            )
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
