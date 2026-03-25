"""SambaWave 도매몰 소싱 API router.

도매몰(domeme, ownerclan 등) 상품 검색 및 저장된 도매 상품 목록을 제공한다.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency

router = APIRouter(prefix="/wholesale", tags=["samba-wholesale"])


# ── Pydantic 요청 모델 ──────────────────────────────────────────────────────


class WholesaleSearchRequest(BaseModel):
    """도매몰 상품 검색 요청 모델."""

    source: str  # 도매몰 구분: domeme, ownerclan 등
    keyword: str  # 검색 키워드
    page: int = 1  # 페이지 번호 (기본 1)


# ── 서비스 팩토리 ──────────────────────────────────────────────────────────


def _write_service(session: AsyncSession):
    """쓰기 세션용 WholesaleService 생성."""
    from backend.domain.samba.wholesale.service import WholesaleService

    return WholesaleService(session)


def _read_service(session: AsyncSession):
    """읽기 세션용 WholesaleService 생성."""
    from backend.domain.samba.wholesale.service import WholesaleService

    return WholesaleService(session)


# ── 엔드포인트 ─────────────────────────────────────────────────────────────


@router.post('/search')
async def search_wholesale(
    body: WholesaleSearchRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """도매몰 상품 검색 후 DB 저장.

    지정한 도매몰(source)에서 키워드로 상품을 검색하고 결과를 저장한다.
    """
    svc = _write_service(session)
    try:
        items = await svc.search_and_save(
            source=body.source,
            keyword=body.keyword,
            page=body.page,
        )
        return {'saved': len(items), 'items': items}
    finally:
        await svc.close()


@router.get('/products')
async def list_wholesale_products(
    source: Optional[str] = Query(None, description='도매몰 구분 (domeme, ownerclan 등)'),
    keyword: Optional[str] = Query(None, description='상품명 키워드 필터'),
    page: int = Query(1, ge=1, description='페이지 번호'),
    size: int = Query(20, ge=1, le=100, description='페이지 크기'),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """저장된 도매 상품 목록 조회.

    필터(source, keyword)와 페이지네이션(page, size)을 지원한다.
    """
    svc = _read_service(session)
    items = await svc.list_products(
        source=source,
        keyword=keyword,
        page=page,
        size=size,
    )
    return {'items': items, 'page': page, 'size': size}
