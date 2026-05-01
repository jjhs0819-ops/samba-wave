"""AI + 룰 기반 카테고리 제안 Mixin."""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List

from backend.domain.samba.category.rules import (
    MARKET_CATEGORIES,
    _filter_overseas,
    _filter_to_leaves,
    _gender_balanced_cap,
)

logger = logging.getLogger(__name__)


class CategorySuggestionMixin:
    """카테고리 제안 — DB 동기화 카테고리 기반 키워드 매칭 + AI fallback."""

    async def _get_market_categories(self, market: str) -> List[str]:
        """DB에서 마켓 카테고리를 조회하고, 없으면 하드코딩 fallback. 해외 카테고리 제외."""
        tree = await self.tree_repo.get_by_site(market)
        if tree and tree.cat1:
            cats = _filter_overseas(tree.cat1)
        else:
            cats = _filter_overseas(MARKET_CATEGORIES.get(market, []))
        # 마켓별 거래처 미허용 카테고리 원천 차단 (AI 매핑 후보에서 제거)
        return _apply_market_blocklist(market, cats)


# ──────────────────────────────────────────────────────────────────────────
# 마켓별 차단 카테고리 (AI 매핑 후보에서 원천 제거)
# 추가 시 lotteon plugin의 런타임 우회 코드와 동기화 필요
# ──────────────────────────────────────────────────────────────────────────
def _apply_market_blocklist(market: str, cats: List[str]) -> List[str]:
    """거래처 권한·정책으로 사용 불가한 카테고리를 후보 목록에서 제거."""
    if market != "lotteon":
        return cats
    filtered: List[str] = []
    for c in cats:
        # FC05 패션의류 권한 없음 — AI는 스포츠의류로만 매핑하도록 강제
        if c.startswith("패션의류"):
            continue
        # 거래처 미허용 다운/패딩 (FC08090202 등) — 마지막 세그먼트 키워드 검사
        last = c.split(">")[-1].strip() if ">" in c else c
        if any(kw in last for kw in ("패딩", "다운")):
            continue
        filtered.append(c)
    return filtered

    async def suggest_category(
        self, source_category: str, target_market: str
    ) -> List[str]:
        """카테고리 추천 — DB(API 동기화) 카테고리에서 키워드 매칭.

        1. DB에 동기화된 마켓 카테고리(cat1)에서 가중치 키워드 매칭
        2. cat2(코드맵)가 있으면 코드맵 키에서도 매칭 (실제 API 카테고리)
        3. AI fallback은 사용하지 않음 — 동기화된 카테고리만 사용
        """
        if not source_category:
            return []

        # 소싱처 ↔ 마켓 간 용어 차이 보완 (동의어 확장)
        SYNONYMS: Dict[str, List[str]] = {
            "아우터": ["재킷", "점퍼", "코트", "자켓", "바람막이", "패딩", "야상"],
            "상의": ["티셔츠", "셔츠", "니트", "맨투맨", "후드티", "블라우스"],
            "하의": ["바지", "팬츠", "슬랙스", "청바지", "레깅스", "치마"],
            "신발": ["스니커즈", "운동화", "구두", "부츠", "샌들", "슬리퍼"],
            "가방": ["백팩", "크로스백", "토트백", "숄더백", "클러치"],
            "데님": ["청바지", "진"],  # 데님 팬츠 → 청바지 카테고리 매핑 보완
            "조거": [
                "트레이닝팬츠",
                "스포츠팬츠",
            ],  # 조거/트레이닝 팬츠 카테고리 매핑 보완
        }

        raw_keywords = [
            k.strip()
            for k in re.split(r"[>/\s]+", source_category.lower())
            if len(k.strip()) > 1
        ]
        # 동의어 확장
        keywords = list(raw_keywords)
        for kw in raw_keywords:
            if kw in SYNONYMS:
                keywords.extend(SYNONYMS[kw])
        if not keywords:
            return []

        # DB에서 카테고리 목록 조회 (리프만 — 비-리프 매핑 방지)
        categories = _filter_to_leaves(await self._get_market_categories(target_market))
        if not categories:
            logger.warning(
                "[카테고리 추천] %s: 동기화된 카테고리 없음 — 카테고리 동기화를 먼저 실행해주세요",
                target_market,
            )
            return []

        # 가중치 키워드 매칭
        # 원본 키워드: 높은 가중치, 동의어: 낮은 가중치
        original_set = set(raw_keywords)
        scored = []
        for cat in categories:
            lower_cat = cat.lower()
            score = 0
            for kw in keywords:
                weight = 3 if kw in original_set else 1  # 원본=3, 동의어=1
                if kw in lower_cat:
                    score += weight * 2
                else:
                    segments = [s.strip() for s in re.split(r"[>/\s]+", lower_cat)]
                    for seg in segments:
                        if seg and (kw in seg or seg in kw):
                            score += weight
                            break
            if score > 0:
                scored.append((cat, score))

        scored.sort(key=lambda x: (-x[1], len(x[0])))
        # 성별 균등 노출 — 11번가처럼 한 성별 leaf 세분화가 더 많은 마켓에서
        # 상위 N개가 한 성별로 도배되는 편향 방지 (rules._gender_balanced_cap)
        return _gender_balanced_cap([cat for cat, _ in scored], limit=50)

    async def _ai_suggest_categories(
        self, keyword: str, target_market: str
    ) -> List[str]:
        """AI로 마켓 카테고리 추천 (suggest_category fallback용)."""
        from backend.core.config import settings

        key = settings.anthropic_api_key
        if not key:
            # DB settings에서도 시도
            try:
                from backend.domain.samba.forbidden.repository import (
                    SambaSettingsRepository,
                )

                repo = SambaSettingsRepository(self.mapping_repo.session)
                row = await repo.find_by_async(key="claude")
                if row and isinstance(row.value, dict):
                    key = row.value.get("apiKey", "")
            except Exception:
                pass
        if not key:
            return []

        import anthropic

        market_label = {
            "smartstore": "네이버 스마트스토어",
            "coupang": "쿠팡",
            "gmarket": "G마켓",
            "auction": "옥션",
            "11st": "11번가",
            "ssg": "SSG(신세계)",
            "lotteon": "롯데ON",
            "lottehome": "롯데홈쇼핑",
            "gsshop": "GS샵",
            "homeand": "홈앤쇼핑",
            "hmall": "HMALL(현대)",
            "kream": "KREAM",
        }.get(target_market, target_market)

        prompt = f""""{keyword}" 검색어로 {market_label}에서 매칭되는 실제 카테고리 경로를 최대 10개 추천해주세요.

규칙:
1. {market_label}에 실제로 존재하는 카테고리만 사용하세요.
2. "대분류 > 중분류 > 소분류 > 세분류" 형태의 전체 경로로 작성하세요.
3. 관련도 높은 순서대로 나열하세요.
4. JSON 배열만 응답하세요 (설명 불필요).

예시 형식: ["뷰티 > 메이크업 > 블러셔", "뷰티 > 메이크업 > 치크"]"""

        try:
            client = anthropic.AsyncAnthropic(api_key=key)
            # 429 rate limit 대비 재시도
            for attempt in range(3):
                try:
                    response = await client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=512,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    break
                except anthropic.RateLimitError:
                    if attempt < 2:
                        import asyncio

                        await asyncio.sleep(60 * (attempt + 1))
                    else:
                        raise
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3].strip()
            result = json.loads(text)
            if isinstance(result, list):
                return _filter_overseas([str(c) for c in result[:10]])
            return []
        except Exception as e:
            logger.warning("AI 카테고리 추천 실패 (%s): %s", target_market, e)
            return []

    async def get_market_category_list(self, market: str) -> List[str]:
        """마켓 카테고리 목록 조회 (DB 우선)."""
        return await self._get_market_categories(market)
