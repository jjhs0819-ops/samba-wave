"""빈 칸 행 + 트리 leaf 부분문자열 매칭 후보 (마지막 세그먼트 기반)."""

import asyncio
import asyncpg
import json
import re
import sys
from backend.core.config import settings


TARGET_MARKETS = [
    "11st",
    "auction",
    "coupang",
    "gmarket",
    "lotteon",
    "smartstore",
    "ssg",
]

ALWAYS_BLOCK = (
    "해외직구",
    "롯데임직원몰",
    "비즈11번가",
    "도서/음반",
    "도서 > 잡지",
    "DVD",
    "PC게임",
    "만화",
    "백화점/제화상품권",
    "상품권",
    "장난감/완구",
    "스포츠/캐릭터시계",
    "캐릭터시계",
    "성인용품",
    "콘돔",
    "관상어",
    "쥬얼리/시계 > 스포츠",
)
KIDS_KW = (
    "영유아동",
    "유아동",
    "베이비",
    "키즈 의류",
    "주니어 의류",
    "유아동 ",
    "신생아/유아",
    "아동/주니어",
    "남아",
    "여아",
    "유아동잡화",
    "유아동신발",
)
PET_KW = ("강아지", "반려동물", "반려/애완", "고양이", "햄스터")
MATERNITY_KW = ("임산부", "임부복", "수유")

KIDS_SRC = ("유아동", "아동", "주니어", "키즈", "베이비", "유아", "키덜트")
PET_SRC = ("강아지", "반려동물", "고양이", "반려/애완", "반려")
MATERNITY_SRC = ("임산부", "임부", "수유")


def is_kids_src(s):
    sl = s.lower()
    return any(kw in sl for kw in KIDS_SRC)


def is_pet_src(s):
    sl = s.lower()
    return any(kw in sl for kw in PET_SRC)


def is_maternity_src(s):
    sl = s.lower()
    return any(kw in sl for kw in MATERNITY_SRC)


def filter_to_leaves(categories):
    parent_set = set()
    for c in categories:
        parts = c.split(" > ")
        for i in range(1, len(parts)):
            parent_set.add(" > ".join(parts[:i]))
    return [c for c in categories if c not in parent_set]


def block_check(path, src):
    for kw in ALWAYS_BLOCK:
        if kw in path:
            return True
    if not is_kids_src(src):
        for kw in KIDS_KW:
            if kw in path:
                return True
    if not is_pet_src(src):
        for kw in PET_KW:
            if kw in path:
                return True
    if not is_maternity_src(src):
        for kw in MATERNITY_KW:
            if kw in path:
                return True
    return False


def extract_keywords(source_category):
    """source_category에서 마지막 세그먼트 + 분해된 단어 + 동의어 추출."""
    SYN = {
        "아우터": ["재킷", "점퍼", "코트", "자켓", "바람막이", "패딩", "야상"],
        "상의": ["티셔츠", "셔츠", "니트", "맨투맨", "후드티", "블라우스"],
        "하의": ["바지", "팬츠", "슬랙스", "청바지", "레깅스", "치마"],
        "신발": ["스니커즈", "운동화", "구두", "부츠", "샌들", "슬리퍼"],
        "가방": ["백팩", "크로스백", "토트백", "숄더백", "클러치"],
        "데님": ["청바지", "진"],
        "조거": ["트레이닝팬츠"],
        "가디건": ["카디건"],
        "카디건": ["가디건"],
    }
    parts = [p.strip() for p in source_category.split(">") if p.strip()]
    last = parts[-1] if parts else ""
    # 마지막 세그먼트 + 분해
    sub_words = re.split(r"[/\s]+", last)
    keys = set()
    keys.add(last)
    for w in sub_words:
        if len(w) >= 2:
            keys.add(w)
            if w in SYN:
                keys.update(SYN[w])
    return list(keys), last


def find_candidates(source_category, leaves, src_full, n=15):
    """마지막 세그먼트 또는 분해 키워드를 trip path에 포함하는 leaf 검색.

    부분문자열 매칭으로 후보 풀 확장.
    """
    keys, last = extract_keywords(source_category)
    scored = []
    for c in leaves:
        if block_check(c, src_full):
            continue
        # 마지막 세그먼트 substring 매칭
        score = 0
        if last and last in c:
            score += 10
        for k in keys:
            if k in c:
                score += 3
        # 짧은 path 우선 (구체성)
        if score > 0:
            scored.append((score, len(c), c))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [c for _, _, c in scored[:n]]


async def main(site_filter=None):
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        tree_rows = await conn.fetch(
            "SELECT site_name, cat1, cat2 FROM samba_category_tree"
        )
        market_leaves = {}
        for r in tree_rows:
            cat1 = r["cat1"]
            cat2 = r["cat2"]
            if isinstance(cat1, str):
                try:
                    cat1 = json.loads(cat1)
                except Exception:
                    cat1 = None
            if isinstance(cat2, str):
                try:
                    cat2 = json.loads(cat2)
                except Exception:
                    cat2 = None
            paths = []
            seen = set()
            if isinstance(cat1, list):
                for c in cat1:
                    if isinstance(c, str) and c not in seen:
                        paths.append(c)
                        seen.add(c)
            if isinstance(cat2, dict):
                for k in cat2.keys():
                    if isinstance(k, str) and k not in seen:
                        paths.append(k)
                        seen.add(k)
            elif isinstance(cat2, list):
                for c in cat2:
                    if isinstance(c, str) and c not in seen:
                        paths.append(c)
                        seen.add(c)
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
            missing = [
                mk
                for mk in TARGET_MARKETS
                if not (isinstance(tm.get(mk), str) and tm.get(mk).strip())
            ]
            if not missing:
                continue
            entry = {
                "id": r["id"],
                "source_site": r["source_site"],
                "source_category": r["source_category"],
                "missing": missing,
                "candidates": {},
            }
            src_full = f"{r['source_site']} > {r['source_category']}"
            for mk in missing:
                cands = find_candidates(
                    r["source_category"], market_leaves.get(mk, []), src_full, n=8
                )
                entry["candidates"][mk] = cands
            out.append(entry)

        with open("/tmp/empty_v2.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"행 수: {len(out)}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
