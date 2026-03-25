"""SambaWave Wholesale service - 도매몰 상품 수집 및 조회 비즈니스 로직."""

from typing import Any, Dict, List, Optional

from backend.domain.samba.wholesale.model import SambaWholesaleProduct
from backend.domain.samba.wholesale.repository import SambaWholesaleProductRepository
from backend.utils.logger import logger


class WholesaleService:
    """도매몰 상품 수집/조회 서비스."""

    def __init__(self, repo: SambaWholesaleProductRepository) -> None:
        self._repo = repo

    async def search_and_save(
        self,
        source: str,
        keyword: str,
        page: int = 1,
    ) -> Dict[str, Any]:
        """도매몰 검색 결과를 수집해 DB에 저장.

        Args:
            source: 도매몰 구분 (domeme, ownerclan 등)
            keyword: 검색 키워드
            page: 페이지 번호

        Returns:
            수집 결과 요약 딕셔너리
        """
        logger.info(f"도매몰 검색 시작 — source={source} keyword={keyword} page={page}")

        # TODO: 각 소싱처별 플러그인 연동 (domeme, ownerclan 크롤러)
        # 현재는 스텁 응답 반환
        return {
            "source": source,
            "keyword": keyword,
            "page": page,
            "saved": 0,
            "message": f"{source} 소싱처 플러그인 미구현 (스텁)",
        }

    async def list_wholesale_products(
        self,
        source: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """도매 상품 목록 조회 (필터 + 페이지네이션).

        Args:
            source: 도매몰 구분 필터 (없으면 전체)
            keyword: 상품명 키워드 필터
            page: 페이지 번호 (1-based)
            size: 페이지 크기

        Returns:
            { items: [...], total: int, page: int, size: int }
        """
        from sqlmodel import select, func
        from sqlalchemy import and_

        offset = (page - 1) * size

        # 동적 where 조건 구성
        conditions = []
        if source:
            conditions.append(SambaWholesaleProduct.source_mall == source)
        if keyword:
            conditions.append(SambaWholesaleProduct.name.ilike(f"%{keyword}%"))

        # 총 건수 조회
        count_stmt = select(func.count(SambaWholesaleProduct.id))
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        count_result = await self._repo.session.execute(count_stmt)
        total: int = count_result.scalar() or 0

        # 목록 조회
        list_stmt = (
            select(SambaWholesaleProduct)
            .order_by(SambaWholesaleProduct.collected_at.desc())
            .offset(offset)
            .limit(size)
        )
        if conditions:
            list_stmt = list_stmt.where(and_(*conditions))
        list_result = await self._repo.session.execute(list_stmt)
        items: List[SambaWholesaleProduct] = list(list_result.scalars().all())

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        }
