"""마스마룰즈 관련 활성 잡 확인."""

import asyncio
from sqlalchemy import select, func
from backend.db.orm import get_read_session
from backend.domain.samba.job.model import SambaJob
from backend.domain.samba.collector.model import SambaCollectedProduct as CP


async def main() -> None:
    async with get_read_session() as session:
        # 마스마룰즈 product id 집합
        like = func.btrim(CP.brand).ilike("%마스마룰즈%") | func.btrim(CP.brand).ilike(
            "%masmarulez%"
        )
        pid_rows = (await session.execute(select(CP.id).where(like))).all()
        pid_set = {r[0] for r in pid_rows}
        print(f"마스마룰즈 상품 ID 수: {len(pid_set)}")

        # 활성 잡 (pending/running)
        stmt = select(SambaJob).where(
            SambaJob.status.in_(["pending", "running", "queued"])
        )
        rows = (await session.execute(stmt)).scalars().all()
        print(f"\n활성 잡 총 {len(rows)}개")
        related = []
        for j in rows:
            payload = j.payload or {}
            jpids = payload.get("product_ids") or payload.get("productIds") or []
            if isinstance(jpids, list):
                hit = [p for p in jpids if p in pid_set]
                if hit:
                    related.append((j, len(hit), len(jpids)))

        print(f"\n마스마룰즈 관련 잡: {len(related)}")
        for j, hit, total in related[:20]:
            print(
                f"  id={j.id[:14]} type={j.job_type} status={j.status} progress={j.progress} 마스마룰즈/전체={hit}/{total}"
            )

        # 잡 type별 카운트
        from collections import Counter

        type_count = Counter((j.job_type, j.status) for j in rows)
        print("\n전체 활성 잡 type/status 분포 (top 20):")
        for k, v in type_count.most_common(20):
            print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
