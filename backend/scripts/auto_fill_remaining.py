"""LLM 직접 결정 정책 코드화 — 잔여 빈 칸 자동 채우기.

정책 (LLM이 ABCmart/Nike/GSShop 73행 직접 검토하며 도출):
1. 후보 top4 중 부적합 차단 키워드를 가진 leaf 제외:
   - 영유아동/유아동(0~17세)/베이비/유아/아동(주니어 포함) — source가 키즈류 아니면
   - 해외직구, 롯데임직원몰, 비즈11번가
   - 도서/음반, 도서 > 잡지, DVD, PC게임, 만화
   - 백화점/제화상품권, 상품권
   - 쥬얼리/시계 > 스포츠시계 (스포츠용품 검색 시 시계 잘못 매핑)
   - 장난감/완구 (스포츠 검색 시)
   - 강아지용품, 반려동물 (source가 반려동물 아니면)
   - 임산부/임부복 (source가 임부 아니면)
2. source_category에 키즈 키워드(유아/아동/주니어/키즈/베이비) 포함이면:
   → 키즈 후보 통과시키고 비키즈 후보 차단
3. source_category에 임부 키워드 포함이면 임부 후보 통과
4. 필터링 후 남은 후보의 첫 번째(점수 최상위) 자동 선택
5. 모두 차단되면 SKIP
6. 트리 sanitize 통과만 실제 저장 (이중 안전장치)
"""

import asyncio
import asyncpg
import json
import re
import sys
from collections import defaultdict
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

# 차단 키워드 (leaf path에 들어가면 비키즈/비반려/비임부 source일 때 차단)
KIDS_BLOCK = ("영유아동", "유아동", "베이비", "키즈", "아동", "주니어", "유아", "남아", "여아")
PET_BLOCK = ("강아지", "반려동물", "반려/애완", "고양이", "햄스터")
MATERNITY_BLOCK = ("임산부", "임부복", "임부", "수유")
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
    "광학기기/용품",
    "모서리보호대",
    "유아안전용품",
    "쥬얼리/시계",
    "다트/레저",
    "성인용품",
    "콘돔",
    "스키부츠",  # 스포츠/레저 부츠 매핑에 잘못 들어옴
    "관상어",
    "인테리어/조명/DIY > DIY자재",
)

KIDS_SRC_KW = ("유아동", "아동", "주니어", "키즈", "kids", "junior", "베이비", "baby", "유아")
PET_SRC_KW = ("강아지", "반려동물", "고양이", "반려/애완")
MATERNITY_SRC_KW = ("임산부", "임부", "수유")


def is_kids_source(s: str) -> bool:
    sl = s.lower()
    return any(kw in sl for kw in KIDS_SRC_KW)


def is_pet_source(s: str) -> bool:
    sl = s.lower()
    return any(kw in sl for kw in PET_SRC_KW)


def is_maternity_source(s: str) -> bool:
    sl = s.lower()
    return any(kw in sl for kw in MATERNITY_SRC_KW)


def filter_candidate(path: str, src_cat: str) -> bool:
    """True = 적합, False = 차단."""
    for kw in ALWAYS_BLOCK:
        if kw in path:
            return False
    if not is_kids_source(src_cat):
        for kw in KIDS_BLOCK:
            if kw in path:
                return False
    if not is_pet_source(src_cat):
        for kw in PET_BLOCK:
            if kw in path:
                return False
    if not is_maternity_source(src_cat):
        for kw in MATERNITY_BLOCK:
            if kw in path:
                return False
    return True


def filter_to_leaves(categories):
    parent_set = set()
    for c in categories:
        parts = c.split(" > ")
        for i in range(1, len(parts)):
            parent_set.add(" > ".join(parts[:i]))
    return [c for c in categories if c not in parent_set]


def top_candidates(source_category, leaves, n=8):
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
        # 트리 + valid set + leaves
        tree_rows = await conn.fetch("SELECT site_name, cat1, cat2 FROM samba_category_tree")
        market_leaves = {}
        market_valid = {}
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
            market_valid[r["site_name"]] = set(paths)
            market_leaves[r["site_name"]] = filter_to_leaves(paths)

        sql = "SELECT id, source_site, source_category, target_mappings FROM samba_category_mapping"
        params = []
        if site_filter:
            sql += " WHERE source_site=$1"
            params.append(site_filter)
        rows = await conn.fetch(sql, *params)

        rows_updated = 0
        keys_added = 0
        per_market = defaultdict(int)
        per_site = defaultdict(int)
        skipped_per_market = defaultdict(int)

        async with conn.transaction():
            for r in rows:
                tm = r["target_mappings"]
                if isinstance(tm, str):
                    tm = json.loads(tm)
                if not isinstance(tm, dict):
                    tm = {}
                missing = [
                    mk for mk in TARGET_MARKETS
                    if not (isinstance(tm.get(mk), str) and tm.get(mk).strip())
                ]
                if not missing:
                    continue

                merged = dict(tm)
                added = 0
                for mk in missing:
                    leaves = market_leaves.get(mk, [])
                    cands = top_candidates(r["source_category"], leaves, n=8)
                    chosen = None
                    for c in cands:
                        if filter_candidate(c, r["source_category"]):
                            chosen = c
                            break
                    if not chosen:
                        skipped_per_market[mk] += 1
                        continue
                    if chosen not in market_valid.get(mk, set()):
                        skipped_per_market[mk] += 1
                        continue
                    merged[mk] = chosen
                    added += 1
                    per_market[mk] += 1
                if added:
                    await conn.execute(
                        "UPDATE samba_category_mapping SET target_mappings=$1::jsonb, updated_at=NOW() WHERE id=$2",
                        json.dumps(merged, ensure_ascii=False),
                        r["id"],
                    )
                    rows_updated += 1
                    keys_added += added
                    per_site[r["source_site"]] += 1

        print(f"\n✓ 자동 채움 완료: 행 {rows_updated}, 키 {keys_added}")
        print("\n[마켓별 채움]")
        for m in sorted(per_market.keys()):
            print(f"  {m}: 채움 {per_market[m]}, SKIP {skipped_per_market[m]}")
        print("\n[소싱처별 영향 행]")
        for s in sorted(per_site.keys()):
            print(f"  {s}: {per_site[s]}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
