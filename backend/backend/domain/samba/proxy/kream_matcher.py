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


# ── 버전(에디션) 추출 — 매칭 정확도 핵심 (일/중/영판 혼동 방지) ──
_VERSION_KR_TOKENS = ["일어판", "중문판", "중문", "영문판", "한글판", "대만판"]


def extract_version_kr(name_en: str) -> str:
    """SNKRDUNK 영문명 → 기대 KREAM 버전 토큰. 없으면 ''."""
    low = (name_en or "").lower()
    if "chinese" in low or "(cn)" in low or "tw ver" in low:
        return "중문판"
    if "japanese" in low or "(jp)" in low or "jpn" in low:
        return "일어판"
    if (
        "english" in low
        or "(en)" in low
        or "[en]" in low
        or low.rstrip().endswith(" en")
        or " en " in low
    ):
        return "영문판"
    return ""


# 영문 쿼리/스코어용 — 의미없는 노이즈 단어 제거
_EN_STOP = {
    "card",
    "game",
    "the",
    "card game",
    "tcg",
    "ver",
    "vol",
    "pack",
    "set",
    "promotional",
    "promo",
    "booster",
    "box",
    "edition",
    "and",
    "for",
    "from",
    "unopen",
    "unopened",
    "serial",
    "numbered",
    "prize",
    "participation",
    "japanese",
    "english",
    "chinese",
    "winner",
    "champion",
    "champions",
    "expansion",
    "collection",
    "special",
    "starter",
    "premium",
    "limited",
    "version",
    "deck",
    "kit",
}


def en_content_tokens(name_en: str) -> list[str]:
    """영문명에서 의미있는 토큰(캐릭터/세트어) 추출 — 검색어/스코어용."""
    if not name_en:
        return []
    # 대괄호[코드]만 제거 — 괄호() 안 세트명(EMOTION 등)은 보존
    base = re.sub(r"\[[^\]]*\]", " ", name_en)
    base = re.sub(r"[^A-Za-z0-9.\- ]", " ", base)
    out: list[str] = []
    seen: set[str] = set()
    for w in base.split():
        wl = w.lower().strip(".-")
        if len(wl) < 2 or wl in _EN_STOP or wl.isdigit():
            continue
        if wl not in seen:
            seen.add(wl)
            out.append(wl)
    return out


def build_en_query(name_en: str, style_code: str | None = None) -> str:
    """KREAM 영문 검색어 — 캐릭터/세트 영문어 + (KREAM이 쓰는) 세트코드 품번.

    품번은 KREAM이 실제 쓰는 형식(OP/EB/ST/P-NNN)만 추가 — 정확 변종 surface용.
    SNKRDUNK 내부코드(OPC-/pkmn-/DBSC- 등)는 KREAM에 없어 검색 0 유발 → 제외.
    """
    toks = en_content_tokens(name_en)[:4]
    pnum = normalize_product_number(style_code)
    if pnum and re.match(r"^(OP|EB|ST|PRB|P)\d{0,2}-\d{2,3}$", pnum.upper()):
        toks.append(pnum)
    return " ".join(toks)


def match_candidate(
    name_en: str,
    style_code: str | None,
    cand_text: str,
    rank: int = 0,
) -> tuple[int, bool]:
    """영문명 기반 후보 점수 — 품번 필수 폐기(보너스만), 버전/등급/순위 결합.

    반환 (score, valid). valid=실신호(키워드/영문/품번) 1개+ 있을 때만.
    cand_text = KREAM 검색결과 스니펫(영문 prefix + 한글명).
    """
    cand = cand_text or ""
    cn = _norm(cand)
    cl = cand.lower()
    kws = translate_keywords(name_en)
    rarity = extract_rarity(name_en)
    variants = variant_kr_terms(name_en)
    pnum = normalize_product_number(style_code)
    ver = extract_version_kr(name_en)

    score = 0
    signals = 0
    # 한글 키워드(번역사전) 매칭
    for k in kws:
        if _norm(k) in cn:
            score += 5
            signals += 1
    # 영문 토큰 직접 매칭 (KREAM 영문 prefix/이름에 남은 영문)
    for t in en_content_tokens(name_en):
        if t in cl:
            score += 4
            signals += 1
    # 품번 보너스 (필수 아님)
    if pnum and any(_norm(v) in cn for v in _pnum_variants(pnum)):
        score += 10
        signals += 1
    # 등급 정확매칭
    if rarity and re.search(
        r"(?<![A-Za-z])" + re.escape(rarity) + r"(?![A-Za-z\-])", cand
    ):
        score += 8
    # 버전: 일치 +8, 충돌(다른 버전 표기) -12
    if ver:
        if _norm(ver) in cn or (ver == "중문판" and "중문" in cand):
            score += 8
        else:
            for other in _VERSION_KR_TOKENS:
                if other != ver and _norm(other) in cn:
                    score -= 12
                    break
    # Vol 번호 매칭 (세트 Vol.1/Vol.6 변종 구분)
    mv = re.search(r"vol(?:ume)?\.?\s*(\d+)", name_en or "", re.I)
    if mv:
        vn = mv.group(1)
        if re.search(r"vol\.?\s*0*" + vn + r"(?!\d)", cand, re.I):
            score += 10
        elif re.search(r"vol\.?\s*\d+", cand, re.I):
            score -= 10
    # N주년(anniversary) 매칭 (2nd→2주년, 3rd→3주년)
    ma = re.search(r"(\d+)\s*(?:st|nd|rd|th)\s+anniversar", name_en or "", re.I)
    if ma:
        an = ma.group(1)
        if (an + "주년") in cand:
            score += 10
        elif re.search(r"\d+\s*주년", cand):
            score -= 8
    # 세트/실드 vs 싱글 타입 구분 — 세트 원본이 싱글 후보에 잘못 매칭 방지
    src_is_set = not rarity and bool(
        re.search(r"\b(set|collection|box|deck|loader)\b", name_en or "", re.I)
    )
    if src_is_set:
        if re.search(r"세트|박스|컬렉션|덱|로더", cand):
            score += 6
        elif re.search(r"(?<![A-Za-z])(OP|EB|ST)\d{1,2}-\d{2,3}", cand):
            # 후보가 세트코드 싱글 → 세트 원본과 불일치
            score -= 8
    # 출처/변종
    for v in variants:
        if _norm(v) in cn:
            score += 5
    # 번들 패널티
    if "bundle" not in (name_en or "").lower():
        for vt in _VARIANT_TOKENS_KR:
            if _norm(vt) in cn and not any(_norm(vt) in _norm(k) for k in kws):
                score -= 6
    # KREAM 관련도 순위 보너스 (상위일수록)
    score += max(0, 5 - rank)
    valid = signals >= 1
    return (score, valid)


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


# ── 변종/출처 영→한 (등급 구분용 — query엔 안 쓰고 점수만) ──
VARIANT_EN_KR: dict[str, list[str]] = {
    "serial numbered": ["시리얼"],
    "champion's prize": ["플래그십", "우승", "챔피언"],
    "championship": ["플래그십", "우승", "챔피언"],
    "winner prize": ["우승", "위너"],
    "participation": ["참가"],
    "flagship": ["플래그십"],
    "tournament": ["배틀", "토너먼트", "대회"],
    "store battle": ["스토어", "배틀"],
}

# ── 등급(rarity) 토큰 — KREAM도 동일 영문 표기. 긴 것 우선 매칭 ──
_RARITY_TOKENS = [
    "SEC-P",
    "SEC",
    "SR-P",
    "SR",
    "SCR",
    "UC-P",
    "UC",
    "L-P",
    "R-P",
    "C-P",
    "SP-P",
    "SP",
    "TR",
    "DON",
    "L",
    "R",
    "C",
]


def extract_rarity(name_en: str) -> str:
    """SNKRDUNK 이름의 등급 토큰 추출 (품번 [..] 앞부분에서). 없으면 ''."""
    if not name_en:
        return ""
    head = re.split(r"[\[(]", name_en, 1)[0]
    for tok in _RARITY_TOKENS:  # 긴 것 우선 (SEC-P 가 SEC 보다 먼저)
        if re.search(r"(?<![A-Za-z])" + re.escape(tok) + r"(?![A-Za-z])", head):
            return tok
    return ""


def variant_kr_terms(name_en: str) -> list[str]:
    """출처/변종 한글 키워드 (시리얼/플래그십/우승 등)."""
    if not name_en:
        return []
    low = name_en.lower()
    out: list[str] = []
    seen: set[str] = set()
    for en, kos in VARIANT_EN_KR.items():
        if en in low:
            for k in kos:
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
    rarity: str = "",
    variant_terms: list[str] | None = None,
) -> tuple[int, bool]:
    """후보 점수 + 품번포함여부.

    품번 미포함 → (-1, False) 즉시 제외 신호.
    등급(rarity) 정확매칭 + 출처(시리얼/우승 등) 키워드로 변종 구분.
    """
    cand_norm = _norm(cand_name)
    pnum_hit = any(_norm(v) in cand_norm for v in _pnum_variants(pnum_token))
    if not pnum_hit:
        return (-1, False)
    score = 10  # 품번 일치 기본점
    for k in kr_keywords:
        if _norm(k) in cand_norm:
            score += 5
    # 등급 정확매칭 — KREAM 후보명에 동일 등급 토큰(standalone, -P 구분)
    if rarity:
        if re.search(
            r"(?<![A-Za-z])" + re.escape(rarity) + r"(?![A-Za-z\-])", cand_name
        ):
            score += 8
    # 출처/변종 키워드 (시리얼/플래그십/우승 등) — 변종 동점 깨기
    for v in variant_terms or []:
        if _norm(v) in cand_norm:
            score += 5
    # 번들 패널티: 원본이 번들 아닌데 후보가 번들/덱 등이면 감점
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
    rarity = extract_rarity(name_en)
    variant_terms = variant_kr_terms(name_en)
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
        sc, ok = score_candidate(
            pnum, kr_keywords, is_bundle_src, cname, rarity, variant_terms
        )
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
    # 후보 1개(품번 유일매칭) = 모호성 없음 → 자동 high
    # 또는 점수 충분 + 2등과 격차 확보
    is_high = (len(scored) == 1 and top["score"] >= 10) or (
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
