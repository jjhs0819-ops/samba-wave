"""품절 소스 대체 = 기존 eBay 리스팅 revise [컨테이너 실행, 수수료 0].

기존 상품(product_id)의 번장 소스를 SELLING 다른셀러(new_pid)로 교체 + 원가/이미지 갱신.
새 리스팅 안 만듦(offer가 PUBLISHED면 update_offer=revise). offer ENDED면 재게시=수수료 → 경고.

전제: /tmp/postit.jpg 에 검증완료된 포스트잇 이미지가 있어야 함(postit.py로 먼저 생성+육안확인).

실행:
  docker cp samba-tools/ebay_sourcing/resource.py local-samba-api-1:/tmp/resource.py
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/resource.py \
    <product_id> <new_pid> <new_cost_krw> [account_id]
"""

import asyncio
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.image.service import ImageTransformService
    from backend.domain.samba.proxy.ebay import EbayClient
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlmodel import select

    pid = sys.argv[1]
    new_pid = sys.argv[2]
    new_cost = float(sys.argv[3])
    acc_id = sys.argv[4] if len(sys.argv) > 4 else KV

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            acc = (
                (
                    await s.execute(
                        select(SambaMarketAccount).where(
                            SambaMarketAccount.id == acc_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            addf = acc.additional_fields or {}
            c = EbayClient(
                app_id=addf.get("clientId") or acc.api_key,
                dev_id=addf.get("devId", ""),
                cert_id=addf.get("clientSecret") or acc.api_secret,
                refresh_token=addf.get("oauthToken") or acc.oauth_refresh_token,
            )
            offs = await c.get_offers_by_sku(pid)
            if not offs:
                print("!! offer 없음 — revise 불가(신규는 register.py)")
                return
            o = offs[0]
            before = o.get("listing", {}).get("listingId")
            cat = o.get("categoryId", "")
            if o.get("status") != "PUBLISHED":
                print(
                    f"⚠️ offer status={o.get('status')} (ENDED면 재게시=수수료 발생). 계속하려면 확인 필요."
                )
            # 포스트잇 R2 업로드(검증완료 /tmp/postit.jpg)
            svc = ImageTransformService(s)
            url = await svc._save_image(
                open("/tmp/postit.jpg", "rb").read(),
                f"https://media.bunjang.co.kr/product/{new_pid}_1.jpg",
            )
            # DB 갱신
            p = (
                (
                    await s.execute(
                        select(SambaCollectedProduct).where(
                            SambaCollectedProduct.id == pid
                        )
                    )
                )
                .scalars()
                .first()
            )
            p.source_url = f"https://m.bunjang.co.kr/products/{new_pid}"
            p.site_product_id = new_pid
            p.cost = new_cost
            p.sale_price = new_cost
            p.original_price = new_cost
            p.images = [url]
            p.sale_status = "in_stock"
            s.add(p)
            await s.flush()
            res = await dispatch_to_market(
                s,
                "ebay",
                p.model_dump(),
                category_id=cat,
                account=acc,
                existing_product_no=before,
            )
            print("revise:", json.dumps(res, ensure_ascii=False)[:160])
            await s.commit()
        # 검증: 새 리스팅 여부
        async with get_write_session() as s2:
            acc = (
                (
                    await s2.execute(
                        select(SambaMarketAccount).where(
                            SambaMarketAccount.id == acc_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            addf = acc.additional_fields or {}
            c = EbayClient(
                app_id=addf.get("clientId") or acc.api_key,
                dev_id=addf.get("devId", ""),
                cert_id=addf.get("clientSecret") or acc.api_secret,
                refresh_token=addf.get("oauthToken") or acc.oauth_refresh_token,
            )
            o = (await c.get_offers_by_sku(pid))[0]
            after = o.get("listing", {}).get("listingId")
            print(
                "after:",
                after,
                "price:",
                o.get("pricingSummary", {}).get("price", {}),
                "★",
                ("새리스팅=수수료!" if after != before else "revise=수수료0"),
            )
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
