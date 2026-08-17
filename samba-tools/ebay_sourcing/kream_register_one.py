"""합성사진 1장으로 eBay 1건 등록 [컨테이너 실행].

호스트 배치가 브라우저로 사진을 만든 뒤 건별로 호출한다.
세션은 이 호출 안에서만 열고 닫는다(오염 격리).

인자: <kream_id> <sku> <cost> <img_path> <title_en> <title_ko>
"""

import asyncio
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
CARD_POLICY = "pol_01KXD2K5JE2HHR53GZ1NGV0PGV"  # 이베이_카드 ($9.90 배송)
CATEGORY = "183454"  # TCG 싱글카드


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.image.service import ImageTransformService
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from backend.domain.samba.shipment.service import calc_market_price
    from sqlalchemy import text as t
    from sqlmodel import select

    pid, sku, cost_s, img_path, title_en, title_ko = sys.argv[1:7]
    cost = float(cost_s)

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            url = await ImageTransformService(s)._save_image(open(img_path, "rb").read(), f"{pid}_postit.jpg")

            _pr, _mp = (
                await s.execute(t("SELECT pricing,market_policies FROM samba_policy WHERE id=:i"), {"i": CARD_POLICY})
            ).first()
            _pr = _pr if isinstance(_pr, dict) else json.loads(_pr or "{}")
            _mp = _mp if isinstance(_mp, dict) else json.loads(_mp or "{}")
            sale = float(calc_market_price(cost, _pr, "ebay", _mp) or cost)

            existing = (
                await s.execute(
                    t("SELECT id FROM samba_collected_product WHERE source_site='KREAM' AND site_product_id=:p"),
                    {"p": pid},
                )
            ).first()
            if existing:
                p = (
                    (await s.execute(select(SambaCollectedProduct).where(SambaCollectedProduct.id == existing[0])))
                    .scalars()
                    .first()
                )
            else:
                p = SambaCollectedProduct(
                    source_site="KREAM",
                    tenant_id=TENANT,
                    site_product_id=str(pid),
                    source_url=f"https://kream.co.kr/products/{pid}",
                    registered_accounts=[],
                )
            p.name = title_ko
            p.name_en = title_en
            p.original_price = cost
            p.sale_price = sale
            p.cost = cost
            p.status = "active"
            p.sale_status = "in_stock"
            p.images = [url]
            p.applied_policy_id = CARD_POLICY
            p.style_code = sku
            p.stock_quantities = {KV: 1}
            s.add(p)
            await s.flush()

            acc = (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()
            res = await dispatch_to_market(
                s, "ebay", p.model_dump(), category_id=CATEGORY, account=acc, existing_product_no=""
            )
            if res.get("success"):
                lid = res.get("data", {}).get("listingId") or res.get("product_no")
                p.registered_accounts = [KV]
                p.market_product_nos = {KV: lid}
                s.add(p)
                await s.commit()
                print(f"RESULT OK {lid}")
            else:
                await s.rollback()
                print(f"RESULT FAIL {str(res.get('message'))[:100]}")
    except Exception as e:
        print(f"RESULT FAIL {type(e).__name__}: {str(e)[:100]}")
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
