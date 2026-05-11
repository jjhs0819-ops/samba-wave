#!/usr/bin/env python3
"""
DB 상태 자동 확인 스크립트
Claude가 사람 개입 없이 DB 데이터를 확인하는 용도

사용:
  cd backend && .venv/Scripts/python.exe scripts/check_db.py [쿼리명]
  쿼리명: jobs | products | orders | columns TABLE | count TABLE | raw "SQL"
"""

from __future__ import annotations

import asyncio
import sys
import os

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.config import settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text


def get_engine():
    url = (
        f"postgresql+asyncpg://{settings.write_db_user}:{settings.write_db_password}"
        f"@{settings.write_db_host}:{settings.write_db_port}/{settings.write_db_name}"
    )
    return create_async_engine(url, echo=False)


async def run_query(sql: str, label: str = "결과"):
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text(sql))
        rows = result.fetchall()
        cols = result.keys()
        print(f"\n[ {label} — {len(rows)}행 ]")
        if rows:
            col_list = list(cols)
            # 헤더
            print("  " + " | ".join(f"{c:20}" for c in col_list))
            print("  " + "-" * (23 * len(col_list)))
            for row in rows[:50]:  # 최대 50행 출력
                print("  " + " | ".join(f"{str(v)[:20]:20}" for v in row))
            if len(rows) > 50:
                print(f"  ... ({len(rows) - 50}행 더 있음)")
        else:
            print("  (데이터 없음)")
    await engine.dispose()


QUERIES = {
    "jobs": (
        "SELECT id, type, status, created_at, updated_at "
        "FROM samba_jobs ORDER BY created_at DESC LIMIT 10",
        "최근 Job 10건",
    ),
    "failed-jobs": (
        "SELECT id, type, status, error_message, created_at "
        "FROM samba_jobs WHERE status='failed' ORDER BY created_at DESC LIMIT 10",
        "실패 Job 10건",
    ),
    "products": (
        "SELECT id, source_site, product_name, sale_status, updated_at "
        "FROM samba_products ORDER BY updated_at DESC LIMIT 10",
        "최근 상품 10건",
    ),
    "orders": (
        "SELECT id, market_type, order_status, created_at "
        "FROM samba_orders ORDER BY created_at DESC LIMIT 10",
        "최근 주문 10건",
    ),
    "migrations": ("SELECT version_num FROM alembic_version", "현재 마이그레이션 버전"),
}


async def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "jobs"

    if cmd == "columns" and len(sys.argv) > 2:
        table = sys.argv[2]
        await run_query(
            f"SELECT column_name, data_type, is_nullable "
            f"FROM information_schema.columns "
            f"WHERE table_name='{table}' ORDER BY ordinal_position",
            f"{table} 컬럼 목록",
        )
    elif cmd == "count" and len(sys.argv) > 2:
        table = sys.argv[2]
        await run_query(f"SELECT COUNT(*) as cnt FROM {table}", f"{table} 레코드 수")
    elif cmd == "raw" and len(sys.argv) > 2:
        sql = " ".join(sys.argv[2:])
        await run_query(sql, "직접 쿼리")
    elif cmd in QUERIES:
        sql, label = QUERIES[cmd]
        await run_query(sql, label)
    else:
        print(f"사용 가능한 명령어: {', '.join(QUERIES.keys())}")
        print("  columns TABLE  — 테이블 컬럼 확인")
        print("  count TABLE    — 레코드 수 확인")
        print('  raw "SQL"      — 직접 SQL 실행')
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
