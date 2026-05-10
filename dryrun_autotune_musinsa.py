"""오토튠 경로 드라이런: 5282961 _parse_musinsa 호출 (DB 쓰기 없음)
- 백엔드가 DB의 musinsa 쿠키로 호출했을 때 cost 산출 결과
- 쿠폰 API 응답 raw + 적용된 쿠폰 갯수
"""
import asyncio
import logging
import sys

sys.path.insert(0, "/app/backend")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)


async def main():
    from backend.db.orm import get_read_session
    from sqlalchemy import select
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.collector import refresher

    target_spid = "5282961"

    async with get_read_session() as session:
        stmt = select(SambaCollectedProduct).where(
            SambaCollectedProduct.site_product_id == target_spid,
            SambaCollectedProduct.source_site == "MUSINSA",
        ).limit(1)
        product = (await session.execute(stmt)).scalar_one_or_none()

    if not product:
        print(f"product 5282961 not found")
        return

    print(f"=== DB 현재 상태 ===")
    print(f"  id={product.id} spid={product.site_product_id}")
    print(f"  cost={product.cost}  sale_price={product.sale_price}  original={product.original_price}")
    print(f"  last_refreshed_at={product.last_refreshed_at}")

    print(f"\n=== _parse_musinsa 드라이런 시작 ===")
    result = await refresher._parse_musinsa(product)
    print(f"\n=== 산출 RefreshResult ===")
    print(f"  product_id={result.product_id}")
    print(f"  error={getattr(result, 'error', None)}")
    print(f"  changes={getattr(result, 'changes', None)}")
    print(f"  cost={getattr(result, 'cost', None)}")
    print(f"  sale_price={getattr(result, 'sale_price', None)}")
    print(f"  original_price={getattr(result, 'original_price', None)}")
    print(f"  raw={vars(result) if hasattr(result, '__dict__') else result}")


asyncio.run(main())
