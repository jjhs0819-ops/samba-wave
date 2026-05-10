"""마스마룰즈 17개 검색필터에 대한 수집 잡 생성."""

import asyncio
from sqlalchemy import select
from backend.db.orm import get_write_session
from backend.domain.samba.collector.model import SambaSearchFilter as SF
from backend.domain.samba.job.repository import SambaJobRepository
from backend.domain.samba.job.service import SambaJobService


async def main() -> None:
    async with get_write_session() as session:
        # 마스마룰즈 search_filter 모두 조회
        stmt = select(SF).where(SF.name.like("%마스마룰즈%"))
        rows = (await session.execute(stmt)).scalars().all()
        print(f"마스마룰즈 검색필터 {len(rows)}개")

        job_svc = SambaJobService(SambaJobRepository(session))
        created = []
        for sf in rows:
            payload = {"filter_id": sf.id, "source_site": sf.source_site}
            job = await job_svc.create_job({"job_type": "collect", "payload": payload})
            created.append((sf.name, job.id))
            print(f"  + 잡 생성 {job.id[:14]}: {sf.name}")
        await session.commit()
        print(f"\n총 {len(created)}개 수집 잡 생성 (commit 완료)")


if __name__ == "__main__":
    asyncio.run(main())
