"""v3 — 트리 leaf의 마지막 세그먼트와 source 마지막 세그먼트 매칭 강화 + SYN 대폭 확장."""

import asyncio
import asyncpg
import json
import re
from backend.core.config import settings


TARGETS = ["11st", "auction", "coupang", "gmarket", "lotteon", "smartstore", "ssg"]

# 부적합 차단
BLOCK = (
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
    "신생아/유아",
    "아동/주니어",
    "유아동잡화",
    "유아동신발",
    "유아동가방",
    "남아",
    "여아",
    "아동",
)
PET_KW = ("강아지", "반려동물", "반려/애완", "고양이", "햄스터")
MATERN_KW = ("임산부", "임부복", "수유")
KIDS_S = ("유아동", "아동", "주니어", "키즈", "베이비", "유아", "키덜트")
PET_S = ("강아지", "반려동물", "고양이", "반려/애완")
MATERN_S = ("임산부", "임부", "수유")

# 동의어 대폭 확장 (양방향)
SYN_PAIRS = [
    ("가디건", "카디건"),
    ("서류가방", "브리프케이스"),
    ("볼캡", "야구모자"),
    ("야구모자", "캡"),
    ("등산양말", "양말"),
    ("등산장갑", "장갑"),
    ("스포츠양말", "양말"),
    ("스포츠장갑", "장갑"),
    ("골프양말", "양말"),
    ("스포츠모자", "모자"),
    ("스포츠가방", "가방"),
    ("스포츠벨트", "벨트"),
    ("등산화", "트레킹화"),
    ("등산바지", "긴바지"),
    ("스포츠팬티", "팬티"),
    ("아쿠아슈즈", "메시슈즈"),
    ("구두", "로퍼"),
    ("샌들", "슬리퍼"),
    ("스니커즈", "운동화"),
    ("운동화", "스니커즈"),
    ("백팩", "배낭"),
    ("크로스백", "메신저백"),
    ("토트백", "숄더백"),
    ("쇼퍼백", "토트백"),
    ("핸드백", "토트백"),
    ("후드티", "후드티셔츠"),
    ("후드집업", "집업"),
    ("맨투맨", "스웨트"),
    ("점퍼", "재킷"),
    ("자켓", "재킷"),
    ("바람막이", "윈드브레이커"),
    ("패딩", "다운"),
    ("코트", "롱코트"),
    ("청바지", "데님"),
    ("데님", "청바지"),
    ("팬츠", "바지"),
    ("바지", "팬츠"),
    ("슬랙스", "정장바지"),
    ("반바지", "쇼츠"),
    ("쇼츠", "반바지"),
    ("니트", "스웨터"),
    ("브이넥", "v넥"),
    ("터틀넥", "폴라"),
    ("원피스", "드레스"),
    ("스커트", "치마"),
    ("티셔츠", "티"),
    ("블라우스", "셔츠"),
    ("머플러", "스카프"),
    ("스카프", "머플러"),
    ("선글라스", "안경"),
    ("키링", "가방액세서리"),
    ("벨트", "정장벨트"),
    ("내복", "내의"),
    ("실내화", "슬리퍼"),
    ("부츠", "워커"),
    ("워커", "부츠"),
    ("레인부츠", "장화"),
    ("아대", "보호대"),
    ("기능성", "이너웨어"),
]


def is_src(src, kws):
    sl = src.lower()
    return any(kw in sl for kw in kws)


def filter_to_leaves(cats):
    parents = set()
    for c in cats:
        parts = c.split(" > ")
        for i in range(1, len(parts)):
            parents.add(" > ".join(parts[:i]))
    return [c for c in cats if c not in parents]


def block(path, src):
    for kw in BLOCK:
        if kw in path:
            return True
    if not is_src(src, KIDS_S):
        for kw in KIDS_KW:
            if kw in path:
                return True
    if not is_src(src, PET_S):
        for kw in PET_KW:
            if kw in path:
                return True
    if not is_src(src, MATERN_S):
        for kw in MATERN_KW:
            if kw in path:
                return True
    return False


def expand_syn(words):
    out = set(words)
    for w in list(words):
        for a, b in SYN_PAIRS:
            if w == a:
                out.add(b)
            if w == b:
                out.add(a)
    return out


def find_cands(src_cat, leaves, src_full, n=8):
    parts = [p.strip() for p in src_cat.split(">") if p.strip()]
    last = parts[-1] if parts else ""
    sub = re.split(r"[/\s]+", last)
    keys = set([last] + [w for w in sub if len(w) >= 2])
    keys = expand_syn(keys)

    scored = []
    for c in leaves:
        if block(c, src_full):
            continue
        leaf_last = c.split(" > ")[-1] if " > " in c else c
        score = 0
        # 마지막 세그먼트 정확 매칭
        if last == leaf_last:
            score += 100
        # 마지막 세그먼트 substring
        for k in keys:
            if k and k in leaf_last:
                score += 30
            if k and leaf_last in k:
                score += 20
        # 전체 path 키워드
        for k in keys:
            if k and k in c:
                score += 5
        if score > 0:
            scored.append((score, len(c), c))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [c for _, _, c in scored[:n]]


async def main():
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
            c1, c2 = r["cat1"], r["cat2"]
            if isinstance(c1, str):
                try:
                    c1 = json.loads(c1)
                except:
                    c1 = None
            if isinstance(c2, str):
                try:
                    c2 = json.loads(c2)
                except:
                    c2 = None
            paths = []
            seen = set()
            if isinstance(c1, list):
                for c in c1:
                    if isinstance(c, str) and c not in seen:
                        paths.append(c)
                        seen.add(c)
            if isinstance(c2, dict):
                for k in c2.keys():
                    if isinstance(k, str) and k not in seen:
                        paths.append(k)
                        seen.add(k)
            elif isinstance(c2, list):
                for c in c2:
                    if isinstance(c, str) and c not in seen:
                        paths.append(c)
                        seen.add(c)
            market_leaves[r["site_name"]] = filter_to_leaves(paths)

        rows = await conn.fetch(
            "SELECT id, source_site, source_category, target_mappings FROM samba_category_mapping"
        )
        out = []
        for r in rows:
            tm = r["target_mappings"]
            if isinstance(tm, str):
                tm = json.loads(tm)
            if not isinstance(tm, dict):
                tm = {}
            missing = [
                mk
                for mk in TARGETS
                if not (isinstance(tm.get(mk), str) and tm.get(mk).strip())
            ]
            if not missing:
                continue
            src_full = f"{r['source_site']} > {r['source_category']}"
            entry = {
                "id": r["id"],
                "source_site": r["source_site"],
                "source_category": r["source_category"],
                "candidates": {},
            }
            for mk in missing:
                cands = find_cands(
                    r["source_category"], market_leaves.get(mk, []), src_full, n=8
                )
                entry["candidates"][mk] = cands
            out.append(entry)

        with open("/tmp/empty_v3.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"행: {len(out)}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
