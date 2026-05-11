"""GSShop redirect 감지 동작 검증 — 배포된 컨테이너에서 가짜 prdid 호출."""

import asyncio
from backend.domain.samba.proxy.gsshop_sourcing import (
    GsShopSourcingClient,
    ProductNotFoundError,
)


async def main():
    client = GsShopSourcingClient()

    # 1) 가짜 prdid — ProductNotFoundError 발생해야 정상
    print("[1] 존재하지 않는 prdid=99999999999 호출:")
    try:
        result = await client.get_product_detail("99999999999", refresh_only=True)
        print(
            f"  ❌ 실패: ProductNotFoundError가 발생하지 않음. result keys={list(result.keys()) if result else 'empty'}"
        )
        if result:
            print(
                f"     name={result.get('name')!r} saleStatus={result.get('saleStatus')!r}"
            )
    except ProductNotFoundError as e:
        print(f"  ✅ 성공: ProductNotFoundError 발생 — {e}")
    except Exception as e:
        print(f"  ⚠️ 다른 예외: {type(e).__name__}: {e}")

    # 2) 실제 살아있는 GSShop 상품 1개 — 정상 in_stock 응답이어야 함
    print("\n[2] DB에 있는 실제 GSShop 상품 호출 (정상 응답 확인):")
    import asyncpg
    from backend.core.config import settings

    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.read_db_user,
        password=settings.read_db_password,
        database=settings.read_db_name,
        ssl=False,
    )
    row = await conn.fetchrow(
        "SELECT site_product_id, name FROM samba_collected_product "
        "WHERE source_site='GSShop' AND last_refreshed_at IS NOT NULL "
        "ORDER BY last_refreshed_at DESC LIMIT 1"
    )
    await conn.close()
    if row:
        sid = row["site_product_id"]
        try:
            result = await client.get_product_detail(sid, refresh_only=True)
            print(
                f"  ✅ sid={sid} → name={(result.get('name') or '')[:30]!r}, saleStatus={result.get('saleStatus')!r}, salePrice={result.get('salePrice')}"
            )
        except ProductNotFoundError:
            print(
                f"  ⚠️ sid={sid} → ProductNotFoundError (오탐 가능성). 실제 GS샵 페이지 직접 확인 필요"
            )
        except Exception as e:
            print(f"  ⚠️ sid={sid} 다른 예외: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
