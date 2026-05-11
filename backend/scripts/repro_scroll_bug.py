"""scroll_products 엔드포인트의 conditions 빌딩을 직접 실행해 SQL 캡처."""

import asyncio
from sqlalchemy import select, func, or_, cast, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from backend.core.config import settings
from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
from backend.core.sql_safe import escape_like


async def main():
    # localhost용으로 read pool host 사용
    url = f"postgresql+asyncpg://{settings.write_db_user}:{settings.write_db_password}@{settings.write_db_host}:{settings.write_db_port}/{settings.write_db_name}"
    engine = create_async_engine(url, connect_args={"ssl": False})

    # 백엔드 코드 그대로 시뮬레이션
    search = "나이"
    search_type = "name"
    source_site = "SSG"
    ai_filter = "ai_img_no"

    conditions = []
    q = search.strip()
    q_pat = f"%{escape_like(q)}%"
    q_no_space_pat = f"%{escape_like(q.replace(' ', ''))}%"
    # name search
    conditions.append(
        or_(
            _CP.name.ilike(q_pat, escape="\\"),
            func.replace(_CP.name, " ", "").ilike(q_no_space_pat, escape="\\"),
            _CP.name_en.ilike(q_pat, escape="\\"),
            func.replace(func.coalesce(_CP.name_en, ""), " ", "").ilike(
                q_no_space_pat, escape="\\"
            ),
            func.coalesce(cast(_CP.market_names, String), "").ilike(q_pat, escape="\\"),
            func.coalesce(_CP.brand, "").ilike(q_pat, escape="\\"),
            func.coalesce(_CP.style_code, "").ilike(q_pat, escape="\\"),
            _CP.site_product_id.ilike(q_pat, escape="\\"),
        )
    )
    conditions.append(_CP.source_site == source_site)
    _ai_img = cast('["__ai_image__"]', JSONB)
    if ai_filter == "ai_img_no":
        conditions.append(or_(_CP.tags.is_(None), ~_CP.tags.op("@>")(_ai_img)))

    count_stmt = select(func.count()).select_from(_CP)
    for c in conditions:
        count_stmt = count_stmt.where(c)

    async with AsyncSession(engine) as session:
        # 컴파일된 SQL 출력
        compiled = count_stmt.compile(engine)
        print("=== Compiled SQL ===")
        print(str(compiled))
        print("\n=== Params ===")
        print(compiled.params)
        # 실행
        r = await session.execute(count_stmt)
        print(f"\nCount: {r.scalar()}")

    await engine.dispose()


asyncio.run(main())
