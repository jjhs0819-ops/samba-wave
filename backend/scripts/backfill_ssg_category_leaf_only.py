"""SSG 카테고리 leaf-only 저장 사고 보정 스크립트.

증상: VM 크론잡 SSG 수집 시 확장앱이 본문 DOM 없이 script 태그만 보내서
backend의 breadcrumb regex가 매칭 실패 → cat1=leaf, cat2/3="" 로 저장되고
SambaSearchFilter도 `SSG_<브랜드>_<leaf>` 형태로 leaf-only 생성됨.

해결 로직:
  1. samba_category_tree['SSG'] 의 cat1/cat2/cat3/cat4 트리를 로드.
  2. leaf → 풀패스 reverse map 구축 (대>중>소>세).
  3. samba_collected_product (source_site=SSG, category2 IS NULL/'',
     category1 IS NOT NULL) 대상으로 category1(leaf)을 reverse map 조회.
     유일 매칭 시 category1/2/3/4 풀패스로 재설정.
  4. 연결된 samba_search_filter 의 이름이 `SSG_<brand>_<leaf>` 패턴이고
     풀패스가 유일하게 결정되면 이름을 `SSG_<brand>_<L>_<M>_<S>_<leaf>` 로 rename.
     (이미 같은 이름의 다른 필터가 있으면 rename 생략 — 중복 충돌 방지)
  5. 다중 매칭/매칭 실패 건은 카운트만 기록(수동 검토용).

실행:
  로컬 검증: python backend/scripts/backfill_ssg_category_leaf_only.py --dry-run
  프로덕션 적용:
    scp -i ~/samba-vm-secrets/ssh/deploy_key \
      backend/scripts/backfill_ssg_category_leaf_only.py \
      sbk0674@api.samba-wave.co.kr:/tmp/
    ssh ... sudo docker cp /tmp/backfill_ssg_category_leaf_only.py \
      samba-samba-api-1:/tmp/
    ssh ... sudo docker exec samba-samba-api-1 \
      /app/backend/.venv/bin/python /tmp/backfill_ssg_category_leaf_only.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

import asyncpg

# 프로젝트 루트 경로 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ssg_backfill")


SITE = "SSG"
SAFE_LEAF_BLOCKLIST = {"미분류", "기타", ""}


def normalize(s: str) -> str:
    """공백/특수문자 통일 (비교용)."""
    return re.sub(r"\s+", " ", (s or "")).strip()


def build_leaf_paths(
    cat1: list[str],
    cat2: dict | None,
    cat3: dict | None,
    cat4: dict | None,
) -> dict[str, list[tuple[str, str, str, str]]]:
    """SSG 카테고리 트리에서 leaf 이름 → 풀패스 후보 리스트 생성.

    Returns:
      { "기타 스포츠잡화": [("스포츠웨어/슈즈", "스포츠 잡화", "기타 스포츠잡화", "")] }
    """
    leaf_map: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    cat2 = cat2 or {}
    cat3 = cat3 or {}
    cat4 = cat4 or {}

    for c1 in cat1 or []:
        c2_list = cat2.get(c1) or []
        if not c2_list:
            # 대분류만 있는 경우 자체가 leaf
            leaf_map[normalize(c1)].append((c1, "", "", ""))
            continue
        for c2 in c2_list:
            c3_list = cat3.get(c2) or []
            if not c3_list:
                leaf_map[normalize(c2)].append((c1, c2, "", ""))
                continue
            for c3 in c3_list:
                c4_list = cat4.get(c3) or []
                if not c4_list:
                    leaf_map[normalize(c3)].append((c1, c2, c3, ""))
                    continue
                for c4 in c4_list:
                    leaf_map[normalize(c4)].append((c1, c2, c3, c4))
    return leaf_map


async def load_ssg_tree(conn: asyncpg.Connection) -> dict[str, list[tuple]]:
    row = await conn.fetchrow(
        "SELECT cat1, cat2, cat3, cat4 FROM samba_category_tree WHERE site_name=$1",
        SITE,
    )
    if not row:
        logger.error("samba_category_tree에 SSG 항목 없음 — 보정 불가")
        return {}

    def _j(v):
        if v is None:
            return None
        if isinstance(v, (list, dict)):
            return v
        return json.loads(v)

    cat1 = _j(row["cat1"]) or []
    cat2 = _j(row["cat2"]) or {}
    cat3 = _j(row["cat3"]) or {}
    cat4 = _j(row["cat4"]) or {}
    leaf_map = build_leaf_paths(cat1, cat2, cat3, cat4)
    logger.info(
        "SSG 트리 로드 — leaf 후보 %d개 (1L %d, 2L %d, 3L %d, 4L %d)",
        len(leaf_map),
        len(cat1),
        sum(len(v) for v in cat2.values()) if isinstance(cat2, dict) else 0,
        sum(len(v) for v in cat3.values()) if isinstance(cat3, dict) else 0,
        sum(len(v) for v in cat4.values()) if isinstance(cat4, dict) else 0,
    )
    return leaf_map


async def fix_products(
    conn: asyncpg.Connection,
    leaf_map: dict[str, list[tuple]],
    apply: bool,
) -> tuple[int, int, int, dict[str, int]]:
    """상품 카테고리 풀패스 복원.

    Returns:
      (대상건수, 유일매칭_업데이트, 다중매칭_스킵, leaf별_매칭통계)
    """
    rows = await conn.fetch(
        """
        SELECT id, category1, category2, category3, category4, search_filter_id
        FROM samba_collected_product
        WHERE source_site=$1
          AND (category2 IS NULL OR category2='')
          AND category1 IS NOT NULL AND category1<>''
        """,
        SITE,
    )
    target = len(rows)
    updated = 0
    skipped = 0
    leaf_stats: dict[str, int] = defaultdict(int)
    logger.info("대상 상품 %d건", target)

    for r in rows:
        leaf = normalize(r["category1"])
        if leaf in SAFE_LEAF_BLOCKLIST:
            skipped += 1
            continue
        paths = leaf_map.get(leaf)
        if not paths:
            leaf_stats[f"no_match::{leaf}"] += 1
            skipped += 1
            continue
        if len(paths) > 1:
            leaf_stats[f"ambiguous::{leaf}"] += 1
            skipped += 1
            continue
        c1, c2, c3, c4 = paths[0]
        # leaf-only 였던 row 의 cat1 == leaf 자체이므로, 풀패스 그대로 덮어쓰기
        if apply:
            await conn.execute(
                """
                UPDATE samba_collected_product
                SET category1=$2, category2=$3, category3=$4, category4=$5
                WHERE id=$1
                """,
                r["id"],
                c1,
                c2 or None,
                c3 or None,
                c4 or None,
            )
        updated += 1
        leaf_stats[f"fixed::{leaf}"] += 1

    return target, updated, skipped, leaf_stats


async def fix_search_filters(
    conn: asyncpg.Connection,
    leaf_map: dict[str, list[tuple]],
    apply: bool,
) -> tuple[int, int, int]:
    """검색그룹(SambaSearchFilter) leaf-only 이름을 풀패스로 rename.

    패턴: `SSG_<brand>_<leaf>` (언더스코어 토큰 3개) → leaf 유일 매칭 시 풀패스로 rename.
    """
    rows = await conn.fetch(
        """
        SELECT id, name, tenant_id, parent_id
        FROM samba_search_filter
        WHERE source_site=$1 AND is_folder=false
          AND name LIKE 'SSG\\_%'
        """,
        SITE,
    )
    target = 0
    renamed = 0
    conflicted = 0
    for r in rows:
        nm = r["name"] or ""
        parts = nm.split("_")
        # 'SSG' + brand + leaf → 3 tokens (단, brand 자체에 '_'가 없다고 가정)
        if len(parts) != 3:
            continue
        target += 1
        brand = parts[1]
        leaf = normalize(parts[2])
        if leaf in SAFE_LEAF_BLOCKLIST:
            continue
        paths = leaf_map.get(leaf)
        if not paths or len(paths) != 1:
            continue
        c1, c2, c3, c4 = paths[0]
        new_parts = [p for p in [c1, c2, c3, c4] if p]
        new_name = ("SSG_" + brand + "_" + "_".join(new_parts)).replace("/", "_")
        if new_name == nm:
            continue
        # 동일 이름 충돌 검사 (tenant_id + name 유니크 가정)
        dup = await conn.fetchval(
            """
            SELECT id FROM samba_search_filter
            WHERE source_site=$1 AND name=$2
              AND COALESCE(tenant_id,'')=COALESCE($3,'')
            LIMIT 1
            """,
            SITE,
            new_name,
            r["tenant_id"],
        )
        if dup:
            conflicted += 1
            continue
        if apply:
            await conn.execute(
                "UPDATE samba_search_filter SET name=$2 WHERE id=$1",
                r["id"],
                new_name,
            )
        renamed += 1
    return target, renamed, conflicted


async def main():
    parser = argparse.ArgumentParser()
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--apply", action="store_true", help="실제 DB 업데이트")
    grp.add_argument("--dry-run", action="store_true", help="변경 없이 카운트만")
    args = parser.parse_args()

    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        leaf_map = await load_ssg_tree(conn)
        if not leaf_map:
            return

        if args.apply:
            async with conn.transaction():
                t, u, s, stats = await fix_products(conn, leaf_map, apply=True)
                ft, fr, fc = await fix_search_filters(conn, leaf_map, apply=True)
        else:
            t, u, s, stats = await fix_products(conn, leaf_map, apply=False)
            ft, fr, fc = await fix_search_filters(conn, leaf_map, apply=False)

        logger.info("=" * 60)
        logger.info("상품 보정: 대상 %d / 업데이트 %d / 스킵 %d", t, u, s)
        logger.info("검색그룹 rename: 대상 %d / 변경 %d / 충돌 %d", ft, fr, fc)
        logger.info("=" * 60)

        # 상위 10개 leaf 통계
        top = sorted(stats.items(), key=lambda x: -x[1])[:20]
        for k, v in top:
            logger.info("  %s: %d", k, v)

        mode = "APPLIED" if args.apply else "DRY-RUN"
        logger.info("[%s] 완료", mode)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
