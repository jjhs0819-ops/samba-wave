"""SambaWave Category service."""

from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from backend.domain.samba.category.model import SambaCategoryMapping, SambaCategoryTree
from backend.domain.samba.category.repository import (
    SambaCategoryMappingRepository,
    SambaCategoryTreeRepository,
)

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
