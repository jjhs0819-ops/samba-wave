"""로컬 이미지 파일을 상품 대표이미지로 교체하고 eBay 리스팅까지 수정 [컨테이너 실행].

postit_real.py 로 만든 합성 사진을 실제 리스팅에 반영할 때 쓴다.

실행:
  docker cp samba-tools/ebay_sourcing/apply_image.py local-samba-api-1:/tmp/apply_image.py
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 \
      /tmp/apply_image.py <product_id> /tmp/out.jpg
"""

import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"  # k-tcg_vault. 다른 계정 절대 건드리지 말 것


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.image.service import ImageTransformService
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlmodel import select

    pid, path = sys.argv[1], sys.argv[2]
    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            p = (await s.execute(
                select(SambaCollectedProduct).where(SambaCollectedProduct.id == pid))).scalars().first()
            if not p:
                print(f"실패: 상품 없음 {pid}")
                return
            url = await ImageTransformService(s)._save_image(open(path, "rb").read(), path)
            imgs = list(p.images or [])
            p.images = [url] + [i for i in imgs if i != url][1:]
            s.add(p)
            await s.commit()

            acc = (await s.execute(
                select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()
            no = (p.market_product_nos or {}).get(KV, "")
            res = await dispatch_to_market(s, "ebay", p.model_dump(), category_id="183454",
                                           account=acc, existing_product_no=no)
            print(f"{p.name_en or p.name} → {url}")
            print("eBay 수정", "성공" if res.get("success") else f"실패: {str(res.get('message'))[:80]}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
