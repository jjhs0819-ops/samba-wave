"""마스마룰즈 brand 800건 DB 삭제."""

import asyncio
from sqlalchemy import select, func, delete
from backend.db.orm import get_write_session
from backend.domain.samba.collector.model import SambaCollectedProduct as CP


async def main() -> None:
    async with get_write_session() as session:
        like = func.btrim(CP.brand).ilike("%마스마룰즈%") | func.btrim(CP.brand).ilike(
            "%masmarulez%"
        )

        # 안전 가드 — 마켓 잔존 0건 확인 후에만 삭제
        rows = (
            await session.execute(select(CP.id, CP.registered_accounts).where(like))
        ).all()
        total = len(rows)
        with_reg = sum(
            1
            for r in rows
            if isinstance(r.registered_accounts, list)
            and len(r.registered_accounts) > 0
        )
        print(f"[가드] 마스마룰즈 총 {total}건, 마켓 잔존 {with_reg}건")
        if with_reg > 0:
            print("⚠️ 마켓 잔존이 0이 아님 — 삭제 중단")
            return

        # 삭제 실행
        result = await session.execute(delete(CP).where(like))
        deleted = result.rowcount or 0
        await session.commit()
        print(f"[DB 삭제] {deleted}건 완료")


if __name__ == "__main__":
    asyncio.run(main())
