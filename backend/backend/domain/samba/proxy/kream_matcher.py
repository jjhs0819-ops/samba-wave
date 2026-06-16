"""SNKRDUNK 카드 → KREAM 카탈로그 product_id 매칭.

문제: SNKRDUNK site_product_id ≠ KREAM product_id. KREAM 등록(매도입찰)은 KREAM
카탈로그 product_id가 필요하다. 품번(P-041 등)으로 KREAM을 검색해 찾되, 한 품번에
여러 카드(세트 변종)가 걸리므로 세트/캐릭터명까지 대조해 정확히 골라야 한다.

전략:
  1) 품번 정규화 — 소싱처 접두어(pkmn-tcg-, DBSC-TCG- 등) 제거, 세트-번호 토큰 추출
  2) 영문 SNKRDUNK 이름 → 한글 키워드 변환(KEYWORD_EN_KR) 후 KREAM 후보명과 대조
  3) 후보 점수화: 품번 포함(필수) + 한글 키워드 일치수 − 변종패널티(번들/덱 등)
  4) 1등 점수가 높고 2등과 격차 크면 high-confidence 자동, 아니면 후보목록 반환

KEYWORD_EN_KR: 세션(LLM)이 채우는 영↔한 세트/캐릭터 사전. 미등재 용어는 품번/숫자/
로마자만으로 대조 → 모호하면 needs_review.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

# ── 소싱처 품번 접두어 (제거 대상) ──
_PNUM_PREFIXES = (
    "pkmn-tcg-en-",
    "pkmn-tcg-",
    "DBSC-TCG-",
    "Disny-Lorcana-TCG-JA-",
    "Disny-Lorcana-TCG-",
    "DM-TCG-",
    "YGO-OCG-TCG-",
    "OPC-TCG-",
)

# ── 영문→한글 키워드 사전 (세트/캐릭터/공통어). LLM이 점진 확장 ──
KEYWORD_EN_KR: dict[str, list[str]] = {
    # 공통
    "one piece": ["원피스"],
    "pokemon": ["포켓몬"],
    "dragon ball": ["드래곤볼"],
    "yu-gi-oh": ["유희왕"],
    "promotional card": ["프로모션", "프로모"],
    "promotional": ["프로모션", "프로모"],
    "booster pack": ["부스터", "부스터팩"],
    "booster box": ["부스터박스"],
    "start deck": ["스타트덱", "스타트 덱"],
    "starter deck": ["스타트덱", "스타터덱"],
    "japanese ver": ["일어판"],
    "english ver": ["영문판"],
    "special box": ["스페셜박스", "스페셜 박스"],
    # 세트명
    "emotion": ["이모션"],
    "abyss eye": ["어비스아이", "어비스 아이"],
    # 캐릭터
    "luffy": ["루피"],
    "monkey.d.luffy": ["루피", "몽키"],
    "zoro": ["조로"],
    "nami": ["나미"],
    "boa hancock": ["보아", "행콕"],
    "pikachu": ["피카츄"],
    # 변종 표시
    "gear 5": ["기어5", "기어 5"],
    "gear5": ["기어5", "기어 5"],
}

# 변종/번들 패널티 토큰 (소싱원본에 없는데 후보에 있으면 감점)
_VARIANT_TOKENS_KR = [
    "번들",
    "기어5",
    "기어 5",
    "세븐일레븐",
    "스타트덱",
    "스타트 덱",
    "덱",
]

# 검색어에서 뺄 일반어 (변별력 낮음 — 점수계산엔 유지, 쿼리에선 제외)
_GENERIC_KR = {
    "프로모션",
    "프로모",
    "일어판",
    "영문판",
    "부스터",
    "부스터팩",
    "부스터박스",
    "스페셜박스",
    "스페셜 박스",
    "스타트덱",
    "스타트 덱",
}


# ── SNKRDUNK 컨디션(등급) → KREAM size 라벨 ──
# 확실한 것만 매핑. 미검증 등급은 None → 등록 시 건너뜀(오등록 방지).
#   raw(A/B/C/D) → Ungraded (KREAM은 무등급 1칸으로 통합)
#   PSA 10/9/8 → 동일
#   BGS/ARS/Other Graded → KREAM 실제 size 라벨 미검증 → None(보류)
_CONDITION_TO_KREAM_SIZE: dict[str, str | None] = {
    "A": "Ungraded",
    "B": "Ungraded",
    "C": "Ungraded",
    "D": "Ungraded",
    "기본": "Ungraded",
    "PSA 10": "PSA 10",
    "PSA 9": "PSA 9",
    "PSA 8 or under": "PSA 8",
}


def map_condition_to_kream_size(condition: str | None) -> str | None:
    """SNKRDUNK 컨디션 → KREAM size 라벨. 미검증 등급은 None(등록 건너뜀)."""
    if not condition:
        return None
    return _CONDITION_TO_KREAM_SIZE.get(condition.strip())


def normalize_product_number(style_code: str | None) -> str:
    """소싱처 품번 → KREAM 대조용 핵심 토큰.

    예: pkmn-tcg-SV-P-261 → SV-P-261 / DBSC-TCG-FB10-032 → FB10-032 / P-041 → P-041
    """
    if not style_code:
        return ""
    s = style_code.strip()
    low = s.lower()
    for pref in _PNUM_PREFIXES:
        if low.startswith(pref.lower()):
            s = s[len(pref) :]
            break
    return s.strip(" -")


def _pnum_variants(token: str) -> list[str]:
    """품번 토큰의 매칭 변형 (하이픈/공백 차이 흡수)."""
    if not token:
        return []
    t = token.upper()
    out = {t, t.replace("-", " "), t.replace("-", ""), t.replace(" ", "-")}
    return [v for v in out if v]


def translate_keywords(name_en: str) -> list[str]:
    """영문 SNKRDUNK 이름 → 대조용 한글 키워드 목록 (LLM 사전 기반)."""
    if not name_en:
        return []
    low = name_en.lower()
    kr: list[str] = []
    for en, kos in KEYWORD_EN_KR.items():
        if en in low:
            kr.extend(kos)
    # 중복 제거 (순서 보존)
    seen: set[str] = set()
    out = []
    for k in kr:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").lower())


def score_candidate(
    pnum_token: str,
    kr_keywords: list[str],
    is_bundle_src: bool,
    cand_name: str,
) -> tuple[int, bool]:
    """후보 점수 + 품번포함여부.

    품번 미포함 → (-1, False) 즉시 제외 신호.
    """
    cand_norm = _norm(cand_name)
    pnum_hit = any(_norm(v) in cand_norm for v in _pnum_variants(pnum_token))
    if not pnum_hit:
        return (-1, False)
    score = 10  # 품번 일치 기본점
    for k in kr_keywords:
        if _norm(k) in cand_norm:
            score += 5
    # 변종 패널티: 원본이 번들 아닌데 후보가 번들/덱 등이면 감점
    if not is_bundle_src:
        for vt in _VARIANT_TOKENS_KR:
            if _norm(vt) in cand_norm and not any(
                _norm(vt) in _norm(k) for k in kr_keywords
            ):
                score -= 6
    return (score, True)


async def find_kream_product(
    client: Any,
    style_code: str | None,
    name_en: str,
    brand_hint_kr: str = "",
    high_conf_min: int = 15,
    high_conf_margin: int = 5,
) -> dict[str, Any]:
    """KREAM에서 카드 매칭. {product_id, confidence, score, candidates} 반환.

    confidence: "high"(자동저장 가능) / "low"(후보보류, needs_review)
    """
    pnum = normalize_product_number(style_code)
    kr_keywords = translate_keywords(name_en)
    is_bundle_src = bool(
        re.search(r"bundle|번들|\d+\s*(pcs|cards)", (name_en or "").lower())
    )

    # 검색어: 변별력 높은 키워드(캐릭터/세트) 우선, 일반어(프로모션 등) 제외 + 품번
    distinctive = [k for k in kr_keywords if k not in _GENERIC_KR]
    query_terms = [t for t in (distinctive[:3] + [pnum]) if t]
    keyword = " ".join(query_terms) if query_terms else (pnum or name_en)

    candidates: list[dict[str, Any]] = []
    # KREAM은 빠른 연속 호출 시 500 반환 → 백오프 재시도
    results = None
    last_err = ""
    backoff = 2.0
    for _ in range(3):
        try:
            results = await client.search(keyword, size=30)
            break
        except Exception as e:
            last_err = str(e)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
    if results is None:
        return {
            "product_id": "",
            "confidence": "low",
            "score": 0,
            "candidates": [],
            "error": last_err,
            "pnum": pnum,
            "keyword": keyword,
        }

    scored = []
    for r in results:
        cname = r.get("name", "")
        sc, ok = score_candidate(pnum, kr_keywords, is_bundle_src, cname)
        if not ok:
            continue
        scored.append({"product_id": str(r.get("id", "")), "name": cname, "score": sc})
    scored.sort(key=lambda x: -x["score"])
    candidates = scored[:8]

    if not scored:
        return {
            "product_id": "",
            "confidence": "low",
            "score": 0,
            "candidates": [],
            "pnum": pnum,
            "keyword": keyword,
        }

    top = scored[0]
    second = scored[1]["score"] if len(scored) > 1 else -999
    is_high = (
        top["score"] >= high_conf_min and (top["score"] - second) >= high_conf_margin
    )
    return {
        "product_id": top["product_id"] if is_high else "",
        "best_product_id": top["product_id"],
        "confidence": "high" if is_high else "low",
        "score": top["score"],
        "candidates": candidates,
        "pnum": pnum,
        "keyword": keyword,
    }
