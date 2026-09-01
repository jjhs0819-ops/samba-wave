"""잘못된 정책(pol_kpopgoods_v1, $25배송)을 카드정책으로 수정 + 포스트잇 사진 반영 [컨테이너 실행]."""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
CARD_POLICY = "pol_01KXD2K5JE2HHR53GZ1NGV0PGV"
PRODUCT_ID = "cp_01M04Z5ZRQF5ER358VG6GHGDBB"
SKU = "SV2A200-165"


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.image.service import ImageTransformService
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlmodel import select

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            p = (await s.execute(select(SambaCollectedProduct).where(SambaCollectedProduct.id == PRODUCT_ID))).scalars().first()
            if not p:
                print("!! 상품 못찾음")
                return
            print("교체전 policy:", p.applied_policy_id, "images:", p.images)

            svc = ImageTransformService(s)
            raw = open("/tmp/out_venusaur.jpg", "rb").read()
            url = await svc._save_image(raw, "https://local/venusaur_postit.jpg")
            print("업로드:", url)

            p.applied_policy_id = CARD_POLICY
            p.images = [url]
            s.add(p)
            await s.flush()

            acc = (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()
            res = await dispatch_to_market(
                s, "ebay", p.model_dump(), category_id="183454", account=acc, existing_product_no=SKU,
            )
            print("dispatch:", res.get("success"), res.get("message", "")[:200])
            if res.get("success"):
                await s.commit()
                print("완료")
            else:
                await s.rollback()
                print("실패 — 롤백")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
