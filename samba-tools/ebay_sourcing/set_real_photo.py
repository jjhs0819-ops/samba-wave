"""실사(직접촬영) 사진으로 상품 대표이미지 교체 + eBay revise [컨테이너, 수수료0].

실행:
  docker cp <실사파일> local-samba-api-1:/tmp/<파일>
  docker cp samba-tools/ebay_sourcing/set_real_photo.py local-samba-api-1:/tmp/set_real_photo.py
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/set_real_photo.py <product_id> /tmp/<파일>
"""
import asyncio
import io
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

    sku = sys.argv[1]
    img_path = sys.argv[2]
    product_id = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("ma_") else sku
    acc_id = sys.argv[4] if len(sys.argv) > 4 else (sys.argv[3] if len(sys.argv) > 3 and sys.argv[3].startswith("ma_") else KV)

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            acc = (
                (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == acc_id)))
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
            offs = await ec.get_offers_by_sku(sku)
            before = offs[0].get("listing", {}).get("listingId") if offs else None
            cat = offs[0].get("categoryId", "183454") if offs else "183454"

            svc = ImageTransformService(s)
            raw = open(img_path, "rb").read()
            url = await svc._save_image(raw, "https://local/real_photo.jpg")
            print("업로드:", url)

            p = (
                (await s.execute(select(SambaCollectedProduct).where(SambaCollectedProduct.id == product_id)))
                .scalars()
                .first()
            )
            print("교체전:", p.images)
            p.images = [url]
            s.add(p)
            await s.flush()

            if offs:
                res = await dispatch_to_market(
                    s, "ebay", p.model_dump(), category_id=cat, account=acc, existing_product_no=before
                )
                print("dispatch:", res.get("success"), res.get("message", "")[:100])
            await s.commit()

        if offs:
            offs2 = await ec.get_offers_by_sku(product_id)
            after = offs2[0].get("listing", {}).get("listingId") if offs2 else None
            print("after listingId:", after, "(before:", before, ")", "revise0" if after == before else "★새리스팅!")
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
