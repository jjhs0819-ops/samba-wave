"""SambaWave Category service."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.samba.category.model import SambaCategoryMapping, SambaCategoryTree
from backend.domain.samba.category.repository import (
    SambaCategoryMappingRepository,
    SambaCategoryTreeRepository,
)

logger = logging.getLogger(__name__)

# Market category data ported from js/modules/category.js
MARKET_CATEGORIES: Dict[str, List[str]] = {
    "smartstore": [
        "패션의류 > 남성의류 > 티셔츠",
        "패션의류 > 남성의류 > 청바지",
        "패션의류 > 남성의류 > 아우터",
        "패션의류 > 여성의류 > 원피스",
        "패션의류 > 여성의류 > 블라우스",
        "패션의류 > 남성신발 > 스니커즈",
        "패션의류 > 여성신발 > 부츠",
        "패션잡화 > 가방 > 백팩",
        "패션잡화 > 가방 > 크로스백",
        "스포츠/레저 > 스포츠의류 > 상의",
        "스포츠/레저 > 스포츠신발 > 운동화",
        "뷰티 > 스킨케어 > 토너",
        "뷰티 > 스킨케어 > 에센스",
        "뷰티 > 선케어 > 선크림",
    ],
    "gmarket": [
        "의류/패션 > 남성의류 > 티셔츠/반팔",
        "의류/패션 > 남성의류 > 청바지/팬츠",
        "의류/패션 > 남성신발 > 운동화",
        "의류/패션 > 여성의류 > 원피스/스커트",
        "의류/패션 > 여성신발 > 부츠/힐",
        "뷰티/화장품 > 스킨케어 > 에센스/세럼",
        "스포츠/레저 > 운동화 > 런닝화",
    ],
    "coupang": [
        "패션 > 남성의류 > 상의 > 반팔 티셔츠",
        "패션 > 남성의류 > 하의 > 청바지",
        "패션 > 신발 > 운동화 > 스니커즈",
        "패션 > 여성의류 > 원피스",
        "뷰티 > 스킨케어 > 세럼/에센스",
        "스포츠/레저 > 스포츠의류 > 남성 상의",
    ],
    "ssg": [
        "패션 > 남성패션 > 티셔츠",
        "패션 > 남성패션 > 청바지",
        "패션 > 신발 > 스니커즈",
        "스포츠/아웃도어 > 스포츠신발 > 런닝화",
        "뷰티/헬스 > 기초화장품 > 에센스",
    ],
    "kream": [
        "신발 > 스니커즈 > 농구화",
        "신발 > 스니커즈 > 라이프스타일",
        "신발 > 스니커즈 > 러닝화",
        "신발 > 스니커즈 > 테니스/클래식",
        "신발 > 스포츠화",
        "의류 > 상의 > 반팔 티셔츠",
        "의류 > 상의 > 긴팔 티셔츠",
        "의류 > 상의 > 후드 티셔츠",
        "의류 > 상의 > 맨투맨",
        "의류 > 아우터 > 자켓",
        "의류 > 아우터 > 패딩",
        "의류 > 하의 > 팬츠",
        "가방 > 백팩",
        "가방 > 크로스백",
        "가방 > 토트백",
        "패션잡화 > 모자",
        "패션잡화 > 양말",
        "패션잡화 > 시계",
    ],
}


class SambaCategoryService:
    def __init__(
        self,
        mapping_repo: SambaCategoryMappingRepository,
        tree_repo: SambaCategoryTreeRepository,
    ):
        self.mapping_repo = mapping_repo
        self.tree_repo = tree_repo

    # ==================== Category Mappings ====================

    async def list_mappings(
        self, skip: int = 0, limit: int = 50
    ) -> List[SambaCategoryMapping]:
        return await self.mapping_repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

    async def create_mapping(
        self, data: Dict[str, Any]
    ) -> SambaCategoryMapping:
        return await self.mapping_repo.create_async(**data)

    async def update_mapping(
        self, mapping_id: str, data: Dict[str, Any]
    ) -> Optional[SambaCategoryMapping]:
        return await self.mapping_repo.update_async(mapping_id, **data)

    async def delete_mapping(self, mapping_id: str) -> bool:
        return await self.mapping_repo.delete_async(mapping_id)

    async def find_mapping(
        self, source_site: str, source_category: str
    ) -> Optional[SambaCategoryMapping]:
        return await self.mapping_repo.find_mapping(source_site, source_category)

    # ==================== Category Tree ====================

    async def get_category_tree(
        self, site_name: str
    ) -> Optional[SambaCategoryTree]:
        return await self.tree_repo.get_by_site(site_name)

    async def save_category_tree(
        self, site_name: str, data: Dict[str, Any]
    ) -> SambaCategoryTree:
        existing = await self.tree_repo.get_by_site(site_name)
        if existing:
            for key, value in data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            existing.updated_at = datetime.now(UTC)
            self.tree_repo.session.add(existing)
            await self.tree_repo.session.commit()
            await self.tree_repo.session.refresh(existing)
            return existing
        return await self.tree_repo.create_async(site_name=site_name, **data)

    async def delete_category_tree(self, site_name: str) -> bool:
        return await self.tree_repo.delete_by_site(site_name)

    # ==================== Category Suggestion ====================

    @staticmethod
    def suggest_category(
        source_category: str, target_market: str
    ) -> List[str]:
        """Keyword-based category suggestion.

        Ported from js/modules/category.js suggestCategory().
        Splits the source category into keywords, scores each target market
        category by how many keywords it contains, and returns the top 5.
        """
        categories = MARKET_CATEGORIES.get(target_market, [])
        if not categories or not source_category:
            return []

        # Split on >, whitespace, and / to extract meaningful keywords
        import re

        keywords = [
            k.strip()
            for k in re.split(r"[>/\s]+", source_category.lower())
            if len(k.strip()) > 1
        ]

        if not keywords:
            return categories[:5]

        scored = []
        for cat in categories:
            lower_cat = cat.lower()
            score = sum(1 for kw in keywords if kw in lower_cat)
            scored.append((cat, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [cat for cat, _ in scored[:5]]

    @staticmethod
    def get_market_category_list(market: str) -> List[str]:
        return MARKET_CATEGORIES.get(market, [])

    # ==================== AI Category Suggestion ====================

    @staticmethod
    async def ai_suggest_category(
        source_site: str,
        source_category: str,
        sample_products: List[str],
        target_markets: Optional[List[str]] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, str]:
        """Claude API를 사용하여 소싱 카테고리를 마켓별 카테고리로 매핑 추천.

        Args:
            source_site: 소싱사이트 (예: MUSINSA)
            source_category: 소싱 카테고리 경로 (예: 스니커즈 > 러닝화)
            sample_products: 해당 카테고리의 대표 상품명 목록
            target_markets: 매핑할 마켓 목록 (미지정 시 전체)
            api_key: Claude API 키 (DB에서 조회한 값). 미지정 시 env fallback.

        Returns:
            { market_name: suggested_category } 딕셔너리
        """
        from backend.core.config import settings

        key = api_key or settings.anthropic_api_key
        if not key:
            raise ValueError("ANTHROPIC_API_KEY가 설정되지 않았습니다")

        import anthropic

        markets = target_markets or list(MARKET_CATEGORIES.keys())
        # 요청 마켓 중 카테고리 목록이 있는 것만 필터
        market_cats = {
            m: MARKET_CATEGORIES[m]
            for m in markets
            if m in MARKET_CATEGORIES and MARKET_CATEGORIES[m]
        }

        if not market_cats:
            return {}

        # 프롬프트 구성
        market_list_str = "\n".join(
            f"- {market}: {json.dumps(cats, ensure_ascii=False)}"
            for market, cats in market_cats.items()
        )
        sample_str = ", ".join(sample_products[:5]) if sample_products else "(없음)"

        prompt = f"""소싱 상품의 카테고리를 각 판매 마켓의 카테고리에 매핑해주세요.

[소싱 정보]
- 사이트: {source_site}
- 카테고리: {source_category}
- 대표 상품: {sample_str}

[마켓별 카테고리 목록]
{market_list_str}

규칙:
1. 각 마켓에서 가장 적절한 카테고리를 정확히 1개만 선택하세요.
2. 반드시 위 목록에 있는 카테고리 중에서만 선택하세요.
3. 적절한 카테고리가 없으면 해당 마켓은 빈 문자열로 응답하세요.

JSON만 응답하세요 (설명 불필요):
{json.dumps({m: "" for m in market_cats}, ensure_ascii=False)}"""

        client = anthropic.AsyncAnthropic(api_key=key)

        try:
            response = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            # 응답에서 JSON 추출
            text = response.content[0].text.strip()
            # ```json ... ``` 블록 제거
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3].strip()

            result = json.loads(text)

            # 응답 검증: 실제 카테고리 목록에 있는 값만 유지
            validated: Dict[str, str] = {}
            for market, suggested in result.items():
                if market in market_cats and suggested in market_cats[market]:
                    validated[market] = suggested
                elif market in market_cats:
                    # AI 응답이 목록에 없으면 빈 문자열
                    validated[market] = ""
                    logger.warning(
                        "AI 추천 카테고리 '%s'가 %s 목록에 없음 — 무시",
                        suggested, market,
                    )

            return validated

        except json.JSONDecodeError as e:
            logger.error("AI 응답 JSON 파싱 실패: %s", e)
            raise ValueError(f"AI 응답 파싱 실패: {e}") from e
        except anthropic.APIError as e:
            logger.error("Claude API 오류: %s", e)
            raise ValueError(f"Claude API 오류: {e}") from e

    # ==================== Bulk AI Mapping ====================

    async def bulk_ai_mapping(
        self, api_key: str, session: "AsyncSession"
    ) -> Dict[str, Any]:
        """미매핑 카테고리 자동 매핑 + 기존 매핑 누락 마켓 보충.

        1) 수집 상품 전체에서 고유 (site, leaf_category) 추출
        2) 기존 매핑 전체 조회
        3-A) 미매핑 → AI → 새 매핑 생성
        3-B) 기존 매핑 중 MARKET_CATEGORIES 키 빠진 것 → AI → 매핑 업데이트
        """
        from sqlmodel import select
        from backend.domain.samba.collector.model import SambaCollectedProduct

        all_market_keys = set(MARKET_CATEGORIES.keys())

        # 1) 수집 상품에서 고유 (site, leaf_category, 대표 상품명) 추출
        stmt = select(SambaCollectedProduct)
        result = await session.execute(stmt)
        products = list(result.scalars().all())

        # (site, leaf_path) → 대표 상품명 목록
        cat_samples: Dict[tuple, List[str]] = {}
        for p in products:
            site = p.source_site or ""
            if not site:
                continue
            cats = [p.category1, p.category2, p.category3, p.category4]
            cats = [c for c in cats if c]
            if not cats and p.category:
                cats = [c.strip() for c in p.category.split(">") if c.strip()]
            if not cats:
                continue
            leaf_path = " > ".join(cats)
            key = (site, leaf_path)
            if key not in cat_samples:
                cat_samples[key] = []
            if len(cat_samples[key]) < 5:
                cat_samples[key].append(p.name)

        if not cat_samples:
            return {"mapped": 0, "updated": 0, "skipped": 0, "errors": []}

        # 2) 기존 매핑 전체 조회
        existing_mappings = await self.mapping_repo.list_all()
        existing_map: Dict[tuple, SambaCategoryMapping] = {}
        for m in existing_mappings:
            existing_map[(m.source_site, m.source_category)] = m

        mapped = 0
        updated = 0
        skipped = 0
        errors: List[str] = []

        for (site, leaf_path), samples in cat_samples.items():
            existing = existing_map.get((site, leaf_path))

            if existing:
                # 3-B) 기존 매핑에서 누락 마켓 확인
                current_targets = existing.target_mappings or {}
                missing_markets = all_market_keys - set(current_targets.keys())
                if not missing_markets:
                    skipped += 1
                    continue

                # 누락 마켓만 AI 추천
                try:
                    ai_result = await self.ai_suggest_category(
                        source_site=site,
                        source_category=leaf_path,
                        sample_products=samples,
                        target_markets=list(missing_markets),
                        api_key=api_key,
                    )
                    # 기존 매핑에 추가
                    new_targets = {**current_targets}
                    for market, cat in ai_result.items():
                        if cat:
                            new_targets[market] = cat
                    await self.update_mapping(existing.id, {"target_mappings": new_targets})
                    updated += 1
                except Exception as e:
                    errors.append(f"[보충] {site} > {leaf_path}: {e}")
            else:
                # 3-A) 미매핑 → AI → 새 매핑 생성
                try:
                    ai_result = await self.ai_suggest_category(
                        source_site=site,
                        source_category=leaf_path,
                        sample_products=samples,
                        api_key=api_key,
                    )
                    target_mappings = {m: c for m, c in ai_result.items() if c}
                    if target_mappings:
                        await self.create_mapping({
                            "source_site": site,
                            "source_category": leaf_path,
                            "target_mappings": target_mappings,
                        })
                        mapped += 1
                    else:
                        skipped += 1
                except Exception as e:
                    errors.append(f"[신규] {site} > {leaf_path}: {e}")

        return {"mapped": mapped, "updated": updated, "skipped": skipped, "errors": errors}
