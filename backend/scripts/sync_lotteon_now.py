"""롯데ON 카테고리 즉시 재동기화 (배포 직후 1회용)."""

import asyncio


async def main():
    from backend.db.orm import get_write_sessionmaker
    from backend.domain.samba.category.repository import (
        SambaCategoryMappingRepository,
        SambaCategoryTreeRepository,
    )
    from backend.domain.samba.category.service import SambaCategoryService

    Session = get_write_sessionmaker()
    async with Session() as session:
        svc = SambaCategoryService(
            SambaCategoryMappingRepository(session),
            SambaCategoryTreeRepository(session),
        )
        result = await svc.sync_market_from_api("lotteon", session)
        print("RESULT:", result)

        # 검증: '축구' 포함 leaf 경로 일부 출력
        from sqlmodel import select
        from backend.domain.samba.category.model import SambaCategoryTree

        row = (
            await session.execute(
                select(SambaCategoryTree).where(SambaCategoryTree.site_name == "lotteon")
            )
        ).scalars().first()
        if row and row.cat1:
            soccer = [p for p in row.cat1 if "축구" in p][:20]
            print(f"VERIFY: cat1 total={len(row.cat1)}, '축구' 포함={len(soccer)}개")
            for p in soccer:
                print("  -", p)
        else:
            print("VERIFY: lotteon row 없음")


if __name__ == "__main__":
    asyncio.run(main())
