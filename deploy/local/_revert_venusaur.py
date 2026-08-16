import asyncio, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
PRODUCT_ID = "cp_01M04Z5ZRQF5ER358VG6GHGDBB"
SKU = "SV2A200-165"
ORIGINAL_IMG = "https://api.samba-wave.co.kr/images/transformed/ai_23feb02163b3c2bc.jpg"


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlmodel import select

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            p = (await s.execute(select(SambaCollectedProduct).where(SambaCollectedProduct.id == PRODUCT_ID))).scalars().first()
            p.images = [ORIGINAL_IMG]
            s.add(p)
            await s.flush()
            acc = (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()
            res = await dispatch_to_market(
                s, "ebay", p.model_dump(), category_id="183454", account=acc, existing_product_no=SKU,
            )
            print("dispatch:", res.get("success"), res.get("message", "")[:200])
            if res.get("success"):
                await s.commit()
                print("복구 완료")
            else:
                await s.rollback()
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
