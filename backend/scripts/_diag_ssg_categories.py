"""SSG 카테고리 보정 진단 — DB에서 어떤 데이터가 있는지 확인.

실행:
  sudo docker exec samba-samba-api-1 /app/backend/.venv/bin/python /tmp/_diag_ssg_categories.py
"""

import asyncio
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core.config import settings  # noqa: E402


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        # 1) samba_category_tree site_name 목록
        sites = await conn.fetch(
            "SELECT site_name FROM samba_category_tree ORDER BY site_name"
        )
        print("[category_tree sites]", [r["site_name"] for r in sites])

        # 2) SSG 상품 카테고리 분포 (cat2 빈/존재 카운트)
        leaf_only = await conn.fetchval(
            "SELECT COUNT(*) FROM samba_collected_product "
            "WHERE source_site='SSG' AND (category2 IS NULL OR category2='') "
            "AND category1 IS NOT NULL AND category1<>''"
        )
        full = await conn.fetchval(
            "SELECT COUNT(*) FROM samba_collected_product "
            "WHERE source_site='SSG' AND category2 IS NOT NULL AND category2<>''"
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM samba_collected_product WHERE source_site='SSG'"
        )
        print(
            f"[SSG products] total={total:,} leaf_only={leaf_only:,} full_path={full:,}"
        )

        # 3) leaf-only 상품의 category1 상위 30개
        top_leaves = await conn.fetch(
            """
            SELECT category1, COUNT(*) AS c FROM samba_collected_product
            WHERE source_site='SSG' AND (category2 IS NULL OR category2='')
              AND category1 IS NOT NULL AND category1<>''
            GROUP BY category1 ORDER BY c DESC LIMIT 30
            """
        )
        print("[top leaf-only category1]")
        for r in top_leaves:
            print(f"  {r['category1']}: {r['c']:,}")

        # 4) full-path 상품에서 leaf→풀패스 매핑 (자체 데이터 기반 reverse map)
        full_paths = await conn.fetch(
            """
            SELECT category1, category2, category3, category4, COUNT(*) AS c
            FROM samba_collected_product
            WHERE source_site='SSG' AND category2 IS NOT NULL AND category2<>''
            GROUP BY category1, category2, category3, category4
            """
        )
        print(f"[full-path 조합 수] {len(full_paths)}")

        # 5) SSG 검색그룹 leaf-only 패턴 카운트
        sf_total = await conn.fetchval(
            "SELECT COUNT(*) FROM samba_search_filter WHERE source_site='SSG' AND is_folder=false"
        )
        sf_leaf = await conn.fetchval(
            r"""SELECT COUNT(*) FROM samba_search_filter
            WHERE source_site='SSG' AND is_folder=false
            AND name ~ '^SSG_[^_]+_[^_]+$'"""
        )
        print(f"[SSG search_filter] total={sf_total} leaf-only_pattern={sf_leaf}")

        # 6) leaf-only 검색그룹 샘플 10개
        samples = await conn.fetch(
            r"""SELECT name FROM samba_search_filter
            WHERE source_site='SSG' AND is_folder=false
            AND name ~ '^SSG_[^_]+_[^_]+$'
            LIMIT 10"""
        )
        print("[leaf-only filter samples]")
        for s in samples:
            print(f"  {s['name']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
