"""도매몰 서비스 — 크롤러 호출 후 DB 저장 및 조회."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from backend.domain.samba.wholesale.crawler import WholesaleCrawler
from backend.domain.samba.wholesale.model import SambaWholesaleProduct
from backend.domain.samba.wholesale.repository import SambaWholesaleProductRepository
from backend.utils.logger import logger


class WholesaleService:
    """도매몰 상품 서비스.

    Args:
        session: SQLAlchemy 비동기 세션 (write 세션 사용)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SambaWholesaleProductRepository(session)
        self._crawler = WholesaleCrawler()

    # ──────────────────────────────────────────────
    # 수집 + 저장
    # ──────────────────────────────────────────────

    async def search_and_save(
        self,
        source: str,
        keyword: str,
        page: int = 1,
        tenant_id: Optional[str] = None,
    ) -> List[SambaWholesaleProduct]:
        """도매몰 검색 후 결과를 DB에 저장.

        이미 수집된 상품(source_mall + product_id 중복)은 가격/재고 업데이트만 수행.

        Args:
            source: "domeme" | "ownerclan"
            keyword: 검색어
            page: 검색 페이지 번호
            tenant_id: 테넌트 ID (멀티테넌시)

        Returns:
            저장/업데이트된 SambaWholesaleProduct 목록
        """
        raw_list = await self._crawler.search_products(source, keyword, page=page)
        if not raw_list:
            logger.info(f"[WholesaleService] 검색 결과 없음 — source={source}, keyword={keyword}")
            return []

        saved: List[SambaWholesaleProduct] = []
        now = datetime.now(tz=timezone.utc)

        for item in raw_list:
            product_id = item.get("product_id", "")
            if not product_id:
                continue

            # 중복 수집 방지 — 기존 레코드 조회
            existing = await self._repo.find_by_product_id(source, product_id)

            if existing:
                # 가격·재고 갱신
                existing.price = item.get("price", existing.price)
                existing.retail_price = item.get("retail_price", existing.retail_price)
                existing.image_url = item.get("image_url") or existing.image_url
                existing.updated_at = now
                self._session.add(existing)
                saved.append(existing)
            else:
                # 신규 저장
                product = SambaWholesaleProduct(
                    source_mall=source,
                    product_id=product_id,
                    name=item.get("name", ""),
                    price=item.get("price", 0),
                    retail_price=item.get("retail_price", 0),
                    category=item.get("category"),
                    image_url=item.get("image_url"),
                    detail_url=item.get("detail_url"),
                    tenant_id=tenant_id,
                    collected_at=now,
                    updated_at=now,
                )
                self._session.add(product)
                saved.append(product)

        await self._session.commit()

        # commit 후 refresh (ID 등 DB 기본값 반영)
        for product in saved:
            await self._session.refresh(product)

        logger.info(
            f"[WholesaleService] 저장 완료 — source={source}, keyword={keyword}, count={len(saved)}"
        )
        return saved

    # ──────────────────────────────────────────────
    # 조회
    # ──────────────────────────────────────────────

    async def list_products(
        self,
        source: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        size: int = 50,
        tenant_id: Optional[str] = None,
    ) -> List[SambaWholesaleProduct]:
        """도매몰 상품 목록 조회.

        Args:
            source: 소싱처 필터 ("domeme" | "ownerclan" | None=전체)
            keyword: 상품명 contains 검색 (None=전체)
            page: 페이지 번호 (1-based)
            size: 페이지당 결과 수
            tenant_id: 테넌트 ID 필터 (None=전체)

        Returns:
            SambaWholesaleProduct 목록 (collected_at DESC)
        """
        stmt = select(SambaWholesaleProduct)

        # 소싱처 필터
        if source:
            stmt = stmt.where(SambaWholesaleProduct.source_mall == source)

        # 상품명 키워드 필터
        if keyword:
            stmt = stmt.where(SambaWholesaleProduct.name.contains(keyword))

        # 테넌트 필터
        if tenant_id:
            stmt = stmt.where(SambaWholesaleProduct.tenant_id == tenant_id)

        # 수집 시각 내림차순 정렬
        stmt = stmt.order_by(SambaWholesaleProduct.collected_at.desc())

        # 페이지네이션
        offset = (page - 1) * size
        stmt = stmt.offset(offset).limit(size)

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ──────────────────────────────────────────────
    # 리소스 정리
    # ──────────────────────────────────────────────

    async def close(self) -> None:
        """크롤러 클라이언트 종료."""
        await self._crawler.close()
