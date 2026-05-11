"""마스마룰즈 관련 활성 전송 잡 취소."""

import asyncio
from sqlalchemy import select, func
from backend.db.orm import get_write_session
from backend.domain.samba.job.model import SambaJob
from backend.domain.samba.job.repository import SambaJobRepository
from backend.domain.samba.collector.model import SambaCollectedProduct as CP


async def main() -> None:
    async with get_write_session() as session:
        like = func.btrim(CP.brand).ilike("%마스마룰즈%") | func.btrim(CP.brand).ilike(
            "%masmarulez%"
        )
        pid_rows = (await session.execute(select(CP.id).where(like))).all()
        pid_set = {r[0] for r in pid_rows}

        stmt = select(SambaJob).where(
            SambaJob.status.in_(["pending", "running", "queued"])
        )
        rows = (await session.execute(stmt)).scalars().all()

        repo = SambaJobRepository(session)
        cancelled = 0
        for j in rows:
            payload = j.payload or {}
            jpids = payload.get("product_ids") or payload.get("productIds") or []
            if not isinstance(jpids, list):
                continue
            hit = [p for p in jpids if p in pid_set]
            if hit:
                ok = await repo.cancel_job(j.id)
                print(
                    f"  취소 {'OK' if ok else 'FAIL'}: id={j.id[:14]} type={j.job_type} status={j.status} 마스마룰즈/전체={len(hit)}/{len(jpids)}"
                )
                if ok:
                    cancelled += 1
        await session.commit()
        print(f"\n총 {cancelled}개 잡 취소 (commit 완료)")


if __name__ == "__main__":
    asyncio.run(main())
