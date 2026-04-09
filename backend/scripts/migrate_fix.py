"""프로덕션 DB 누락 컬럼 긴급 패치 — Procfile에서 호출."""

import asyncio
import os


def _env(key):
    return (
        os.environ.get(key)
        or os.environ.get(key.upper())
        or os.environ.get(key.lower())
        or ""
    )


async def fix():
    import asyncpg

    host = _env("WRITE_DB_HOST")
    if not host:
        print("WRITE_DB_HOST not set, skip")
        return
    kw = dict(
        user=_env("WRITE_DB_USER") or "postgres",
        password=_env("WRITE_DB_PASSWORD"),
        database=_env("WRITE_DB_NAME") or "railway",
    )
    if host.startswith("/"):
        kw["host"] = host
    else:
        kw["host"] = host
        kw["port"] = int(_env("WRITE_DB_PORT") or 5432)
    conn = await asyncpg.connect(**kw)
    try:
        await conn.execute(
            "ALTER TABLE samba_search_filter ADD COLUMN IF NOT EXISTS source_brand_name TEXT"
        )
        await conn.execute(
            "ALTER TABLE samba_market_account DROP COLUMN IF EXISTS sort_order"
        )
        print("Schema fix applied.")
    finally:
        await conn.close()


asyncio.run(fix())
