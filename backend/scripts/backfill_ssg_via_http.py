"""SSG 카테고리 leaf-only 보정 — HTTP 직접 fetch로 실시간 풀패스 조회.

backfill_ssg_category_leaf_only.py 가 풀패스 데이터 부족으로 못 푼 leaf-only
잔여 건을 SSG 사이트에서 직접 breadcrumb 을 긁어와 보정한다.

전략:
  1. samba_collected_product 중 SSG · category2 비어있는 그룹별
     (search_filter_id + category1) 대표 source_url 1개씩 추출.
  2. 각 URL HTTP fetch → `data-react-tarea="...카테고리 로케이션|{대|중|소|세}카테고리"
     class="...active"` 패턴으로 풀패스 추출.
  3. 그룹 내 모든 leaf-only 상품에 풀패스 적용 + 검색그룹(SambaSearchFilter)
     leaf-only 이름이면 풀패스 형식으로 rename (중복 충돌 시 스킵).

레이트 리밋: 그룹당 1요청, 요청간 1.0초 sleep.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

import asyncpg
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core.config import settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ssg_http_backfill")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

LEVEL_PATTERNS = {
    "대": re.compile(
        r'data-react-tarea="[^"]*카테고리 로케이션\|대카테고리"\s+class="[^"]*active[^"]*"[^>]*>\s*([^<]+?)\s*<'
    ),
    "중": re.compile(
        r'data-react-tarea="[^"]*카테고리 로케이션\|중카테고리"\s+class="[^"]*active[^"]*"[^>]*>\s*([^<]+?)\s*<'
    ),
    "소": re.compile(
        r'data-react-tarea="[^"]*카테고리 로케이션\|소카테고리"\s+class="[^"]*active[^"]*"[^>]*>\s*([^<]+?)\s*<'
    ),
    "세": re.compile(
        r'data-react-tarea="[^"]*카테고리 로케이션\|세카테고리"\s+class="[^"]*active[^"]*"[^>]*>\s*([^<]+?)\s*<'
    ),
}

SAFE_LEAF_BLOCKLIST = {"미분류", "기타", ""}


def extract_breadcrumb(html: str) -> tuple[str, str, str, str]:
    """active class 가 붙은 카테고리 로케이션 anchor 순차 추출."""
    out = []
    for _lv in ("대", "중", "소", "세"):
        m = LEVEL_PATTERNS[_lv].search(html)
        if m:
            out.append(m.group(1).strip())
        else:
            break
    while len(out) < 4:
        out.append("")
    return tuple(out)  # type: ignore[return-value]


async def fetch_one(
    client: httpx.AsyncClient, url: str, max_retry: int = 4
) -> tuple[str, str, str, str]:
    for attempt in range(max_retry):
        try:
            r = await client.get(url, timeout=20)
            if r.status_code == 429:
                wait = 15 * (attempt + 1)
                logger.warning(
                    "HTTP 429 — %d초 백오프 후 재시도 (%d/%d)",
                    wait,
                    attempt + 1,
                    max_retry,
                )
                await asyncio.sleep(wait)
                continue
            if r.status_code != 200:
                logger.warning("HTTP %d %s", r.status_code, url[:80])
                return ("", "", "", "")
            return extract_breadcrumb(r.text)
        except Exception as e:
            logger.warning("fetch 실패 %s — %s", url[:80], e)
            await asyncio.sleep(5)
    return ("", "", "", "")


async def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="처리 그룹 수 제한 (테스트용)")
    ap.add_argument("--sleep", type=float, default=1.0, help="요청간 sleep(초)")
    args = ap.parse_args()

    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        # 1) 그룹별 대표 URL — (search_filter_id, category1) 별 첫 번째 source_url
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (search_filter_id, category1)
                   search_filter_id, category1, brand, source_url, site_product_id
            FROM samba_collected_product
            WHERE source_site='SSG'
              AND (category2 IS NULL OR category2='')
              AND category1 IS NOT NULL AND category1<>''
              AND source_url IS NOT NULL AND source_url<>''
            ORDER BY search_filter_id, category1, updated_at DESC NULLS LAST
            """
        )
        logger.info("그룹 %d개 (대표 URL 추출 완료)", len(rows))
        if args.limit:
            rows = rows[: args.limit]
            logger.info("--limit %d 적용", args.limit)

        # 2) HTTP fetch 순차 (그룹당 1요청, sleep)
        async with httpx.AsyncClient(
            headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"},
            follow_redirects=True,
        ) as client:
            group_paths: dict[tuple[str | None, str], tuple[str, str, str, str]] = {}
            for idx, r in enumerate(rows, 1):
                key = (r["search_filter_id"], r["category1"])
                path = await fetch_one(client, r["source_url"])
                if path[0]:
                    group_paths[key] = path
                    logger.info(
                        "[%d/%d] %s/%s → %s > %s > %s%s",
                        idx,
                        len(rows),
                        r["brand"] or "-",
                        r["category1"],
                        path[0],
                        path[1] or "",
                        path[2] or "",
                        f" > {path[3]}" if path[3] else "",
                    )
                else:
                    logger.warning(
                        "[%d/%d] %s/%s 풀패스 추출 실패",
                        idx,
                        len(rows),
                        r["brand"] or "-",
                        r["category1"],
                    )
                if idx < len(rows):
                    await asyncio.sleep(args.sleep)

        logger.info("HTTP fetch 완료 — %d개 그룹 풀패스 확보", len(group_paths))

        # 3) 상품 업데이트
        prod_updates = 0
        for (sf_id, cat1), (c1, c2, c3, c4) in group_paths.items():
            if not c2:
                continue  # 풀패스 아니면 의미 없음 (cat2 없이 cat1만이면 leaf-only 그대로)
            if args.apply:
                res = await conn.execute(
                    """
                    UPDATE samba_collected_product
                    SET category1=$1, category2=$2, category3=$3, category4=$4
                    WHERE source_site='SSG'
                      AND search_filter_id IS NOT DISTINCT FROM $5::text
                      AND category1=$6
                      AND (category2 IS NULL OR category2='')
                    """,
                    c1,
                    c2 or None,
                    c3 or None,
                    c4 or None,
                    sf_id,
                    cat1,
                )
                n = int(res.split()[-1]) if res.startswith("UPDATE") else 0
                prod_updates += n
            else:
                n = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM samba_collected_product
                    WHERE source_site='SSG'
                      AND search_filter_id IS NOT DISTINCT FROM $1::text
                      AND category1=$2
                      AND (category2 IS NULL OR category2='')
                    """,
                    sf_id,
                    cat1,
                )
                prod_updates += n or 0

        logger.info("상품 보정: %d건", prod_updates)

        # 4) 검색그룹 rename — leaf-only 패턴 (SSG_<brand>_<leaf>) 만 대상
        sf_rows = await conn.fetch(
            r"""
            SELECT id, name, tenant_id FROM samba_search_filter
            WHERE source_site='SSG' AND is_folder=false
              AND name ~ '^SSG_[^_]+_[^_]+$'
            """
        )
        # leaf → 풀패스 reverse map (group_paths 의 cat1 == leaf 임)
        leaf_to_path: dict[str, set[tuple]] = defaultdict(set)
        for (_sf, leaf), path in group_paths.items():
            if path[1]:
                leaf_to_path[leaf].add(path)

        sf_renamed = 0
        sf_conflict = 0
        for r in sf_rows:
            nm = r["name"]
            parts = nm.split("_")
            if len(parts) != 3:
                continue
            brand, leaf = parts[1], parts[2]
            if leaf in SAFE_LEAF_BLOCKLIST:
                continue
            candidates = leaf_to_path.get(leaf)
            if not candidates or len(candidates) != 1:
                continue
            c1, c2, c3, c4 = next(iter(candidates))
            new_parts = [p for p in [c1, c2, c3, c4] if p]
            new_name = ("SSG_" + brand + "_" + "_".join(new_parts)).replace("/", "_")
            if new_name == nm:
                continue
            dup = await conn.fetchval(
                """
                SELECT id FROM samba_search_filter
                WHERE source_site='SSG' AND name=$1
                  AND COALESCE(tenant_id,'')=COALESCE($2::text,'')
                LIMIT 1
                """,
                new_name,
                r["tenant_id"],
            )
            if dup:
                sf_conflict += 1
                continue
            if args.apply:
                await conn.execute(
                    "UPDATE samba_search_filter SET name=$2 WHERE id=$1",
                    r["id"],
                    new_name,
                )
            sf_renamed += 1

        mode = "APPLIED" if args.apply else "DRY-RUN"
        logger.info("=" * 60)
        logger.info(
            "[%s] 상품 %d건 / 검색그룹 rename %d건 / 충돌 %d건",
            mode,
            prod_updates,
            sf_renamed,
            sf_conflict,
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
