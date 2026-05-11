"""마스마룰즈 브랜드 상품 현황 점검."""

import asyncio
from collections import Counter
from sqlalchemy import select, func

from backend.db.orm import get_read_session
from backend.domain.samba.collector.model import SambaCollectedProduct as CP


async def main() -> None:
    async with get_read_session() as session:
        like_kor = func.btrim(CP.brand).ilike("%마스마룰즈%")
        like_eng = func.btrim(CP.brand).ilike("%masmarulez%")

        stmt = select(
            CP.id,
            CP.brand,
            CP.source_site,
            CP.status,
            CP.registered_accounts,
            CP.market_product_nos,
            CP.name,
        ).where(like_kor | like_eng)
        rows = (await session.execute(stmt)).all()

        total = len(rows)
        with_reg_rows = []
        for r in rows:
            ra = r.registered_accounts
            if isinstance(ra, list) and len(ra) > 0:
                with_reg_rows.append(r)

        print(f"[마스마룰즈] DB 총 {total}건")
        print(f"  - 마켓 등록 잔존(registered_accounts > 0): {len(with_reg_rows)}건")
        print(f"  - 마켓 정리 완료: {total - len(with_reg_rows)}건")

        site_count = Counter(r.source_site for r in with_reg_rows)
        status_count = Counter(r.status for r in with_reg_rows)
        acc_count: Counter = Counter()
        for r in with_reg_rows:
            for aid in r.registered_accounts or []:
                acc_count[aid] += 1
        brand_count = Counter(r.brand for r in rows)

        print(f"\n  brand 컬럼 값 분포: {dict(brand_count)}")
        print(f"  잔존 source_site 분포: {dict(site_count)}")
        print(f"  잔존 status 분포: {dict(status_count)}")
        print("  잔존 등록계정 분포 (top 10):")
        for aid, c in acc_count.most_common(10):
            print(f"    {aid}: {c}건")

        if with_reg_rows:
            print("\n  잔존 샘플 5건:")
            for r in with_reg_rows[:5]:
                regs = r.registered_accounts or []
                nos = r.market_product_nos or {}
                print(
                    f"    id={r.id[:12]} site={r.source_site} status={r.status} regs={len(regs)} nos_keys={len(nos)} name={(r.name or '')[:30]}"
                )


if __name__ == "__main__":
    asyncio.run(main())
