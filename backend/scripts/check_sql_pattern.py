"""백엔드와 동일한 SQLAlchemy cast 패턴이 실제 동작하는지 검증."""

import asyncio
from sqlalchemy import select, func, cast, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from backend.core.config import settings
from backend.domain.samba.collector.model import SambaCollectedProduct as CP


async def main():
    engine = create_async_engine(
        f"postgresql+asyncpg://{settings.read_db_user}:{settings.read_db_password}@{settings.read_db_host}:{settings.read_db_port}/{settings.read_db_name}",
        connect_args={"ssl": False},
    )
    async with AsyncSession(engine) as session:
        # 패턴 A — 백엔드 collector.py:1042가 쓰는 방식
        ai_img_A = cast('["__ai_image__"]', JSONB)
        stmt_A = (
            select(func.count())
            .select_from(CP)
            .where(
                CP.source_site == "SSG",
                or_(CP.tags.is_(None), ~CP.tags.op("@>")(ai_img_A)),
            )
        )
        # 컴파일된 SQL 출력
        compiled = stmt_A.compile(engine)
        print("== Pattern A (cast literal) compiled SQL ==")
        print(str(compiled))
        print("params:", compiled.params)
        r = await session.execute(stmt_A)
        print(f"Pattern A count: {r.scalar()}")

        # 패턴 B — collector.py:693이 쓰는 방식 (text)
        from sqlalchemy import text as _text

        ai_img_B = _text("'[\"__ai_image__\"]'::jsonb")
        stmt_B = (
            select(func.count())
            .select_from(CP)
            .where(
                CP.source_site == "SSG",
                or_(CP.tags.is_(None), ~CP.tags.op("@>")(ai_img_B)),
            )
        )
        compiled_B = stmt_B.compile(engine)
        print("\n== Pattern B (text raw) compiled SQL ==")
        print(str(compiled_B))
        r2 = await session.execute(stmt_B)
        print(f"Pattern B count: {r2.scalar()}")

    await engine.dispose()


asyncio.run(main())
