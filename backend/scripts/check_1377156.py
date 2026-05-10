"""무신사 상품 1377156 DB 저장값 + 라이브 API 응답 점검."""

import asyncio
from sqlalchemy import select

from backend.db.orm import get_read_session
from backend.domain.samba.collector.model import SambaCollectedProduct as CP


async def check_db() -> None:
    async with get_read_session() as session:
        stmt = select(CP).where(
            CP.source_site == "MUSINSA", CP.site_product_id == "1377156"
        )
        rows = (await session.execute(stmt)).scalars().all()
        print(f"[DB] 매칭 {len(rows)}건")
        for p in rows:
            print(f"  id={p.id}")
            print(f"  name={p.name!r}")
            print(f"  brand={p.brand!r}")
            print(f"  style_code={p.style_code!r}")
            print(f"  sex={p.sex!r}")
            print(f"  season={p.season!r}")
            print(f"  manufacturer={p.manufacturer!r}")
            print(f"  origin={p.origin!r}")
            print(f"  color={p.color!r}")
            print(f"  material={(p.material or '')[:60]!r}")


async def check_live() -> None:
    print("\n[라이브 API] MusinsaClient.get_goods_detail('1377156')")
    from backend.domain.samba.proxy.musinsa import MusinsaClient

    client = MusinsaClient()
    try:
        detail = await client.get_goods_detail("1377156")
    except Exception as e:
        print(f"  실패: {type(e).__name__}: {e}")
        return
    if not detail:
        print("  detail = None / empty")
        return
    keys = [
        "style_code",
        "sex",
        "season",
        "manufacturer",
        "origin",
        "color",
        "material",
        "name",
        "brand",
    ]
    for k in keys:
        v = detail.get(k, "<missing>")
        if isinstance(v, str) and len(v) > 80:
            v = v[:80] + "..."
        print(f"  {k}={v!r}")


async def main() -> None:
    await check_db()
    await check_live()


if __name__ == "__main__":
    asyncio.run(main())
