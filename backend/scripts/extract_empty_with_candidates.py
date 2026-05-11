"""빈 칸 행 + 마켓별 트리 후보 top4 추출."""

import asyncio
import asyncpg
import json
import re
import sys
from backend.core.config import settings


TARGET_MARKETS = ["11st", "auction", "coupang", "gmarket", "lotteon", "smartstore", "ssg"]
SYNONYMS = {
    "아우터": ["재킷", "점퍼", "코트", "자켓", "바람막이", "패딩", "야상"],
    "상의": ["티셔츠", "셔츠", "니트", "맨투맨", "후드티", "블라우스"],
    "하의": ["바지", "팬츠", "슬랙스", "청바지", "레깅스", "치마"],
    "신발": ["스니커즈", "운동화", "구두", "부츠", "샌들", "슬리퍼"],
    "가방": ["백팩", "크로스백", "토트백", "숄더백", "클러치"],
    "데님": ["청바지", "진"],
    "조거": ["트레이닝팬츠", "스포츠팬츠"],
}


def filter_to_leaves(categories):
    parent_set = set()
    for c in categories:
        parts = c.split(" > ")
        for i in range(1, len(parts)):
            parent_set.add(" > ".join(parts[:i]))
    return [c for c in categories if c not in parent_set]


def top_candidates(source_category, leaves, n=4):
    raw = [k.strip() for k in re.split(r"[>/\s]+", source_category.lower()) if len(k.strip()) > 1]
    original = set(raw)
    keywords = set(raw)
    for kw in raw:
        if kw in SYNONYMS:
            keywords.update(SYNONYMS[kw])
    scored = []
    for c in leaves:
        lower = c.lower()
        score = 0
        for kw in keywords:
            weight = 3 if kw in original else 1
            if kw in lower:
                score += weight * 2
            else:
                for seg in re.split(r"[>/\s]+", lower):
                    seg = seg.strip()
                    if seg and (kw in seg or seg in kw):
                        score += weight
                        break
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    return [c for _, c in scored[:n]]


async def main(site_filter=None):
    conn = await asyncpg.connect(
        host="172.18.0.2", port=5432,
        user=settings.write_db_user, password=settings.write_db_password,
        database=settings.write_db_name, ssl=False,
    )
    try:
        tree_rows = await conn.fetch("SELECT site_name, cat1, cat2 FROM samba_category_tree")
        market_leaves = {}
        for r in tree_rows:
            cat1 = r["cat1"]; cat2 = r["cat2"]
            if isinstance(cat1, str):
                try: cat1 = json.loads(cat1)
                except Exception: cat1 = None
            if isinstance(cat2, str):
                try: cat2 = json.loads(cat2)
                except Exception: cat2 = None
            paths = []; seen = set()
            if isinstance(cat1, list):
                for c in cat1:
                    if isinstance(c, str) and c not in seen:
                        paths.append(c); seen.add(c)
            if isinstance(cat2, dict):
                for k in cat2.keys():
                    if isinstance(k, str) and k not in seen:
                        paths.append(k); seen.add(k)
            elif isinstance(cat2, list):
                for c in cat2:
                    if isinstance(c, str) and c not in seen:
                        paths.append(c); seen.add(c)
            market_leaves[r["site_name"]] = filter_to_leaves(paths)

        sql = "SELECT id, source_site, source_category, target_mappings FROM samba_category_mapping"
        params = []
        if site_filter:
            sql += " WHERE source_site=$1"
            params.append(site_filter)
        sql += " ORDER BY source_site, source_category"
        rows = await conn.fetch(sql, *params)

        out = []
        for r in rows:
            tm = r["target_mappings"]
            if isinstance(tm, str):
                tm = json.loads(tm)
            if not isinstance(tm, dict):
                tm = {}
            missing = [mk for mk in TARGET_MARKETS if not (isinstance(tm.get(mk), str) and tm.get(mk).strip())]
            if not missing:
                continue
            entry = {
                "id": r["id"],
                "source_site": r["source_site"],
                "source_category": r["source_category"],
                "filled": {mk: tm[mk] for mk in TARGET_MARKETS if isinstance(tm.get(mk), str) and tm[mk].strip()},
                "candidates": {},
            }
            for mk in missing:
                entry["candidates"][mk] = top_candidates(r["source_category"], market_leaves.get(mk, []), n=4)
            out.append(entry)

        with open("/tmp/empty_with_candidates.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"행 수: {len(out)}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
