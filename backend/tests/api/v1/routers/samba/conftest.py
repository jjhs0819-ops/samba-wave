"""Samba collector 라우터 API 테스트용 fixtures.

`async_client` — collector 라우터만 마운트한 경량 FastAPI 앱을 httpx ASGITransport로
감싼 비동기 클라이언트. 실제 app_factory.create_application()은 전체 라우터 +
JWT 인증 미들웨어를 포함해 무겁고, 이 라우터 자체는 JWT 의존성을 갖지 않으므로
(인증은 app_factory의 include_router(..., dependencies=samba_auth)에서 부여됨)
테스트에서는 라우터만 별도로 마운트하고 tenant 의존성만 override한다.

`sample_collected_product` — 실제 DB(samba-db, localhost:5433)에 저장된 최소 상품 row.

`sample_categorized_product` — `category`가 채워진 상품 row. `/products/category-tree`의
휴지통 제외 검증용.

`sample_filtered_product` — 검색필터(`SambaSearchFilter`) 1건 + 그 필터를 참조하는 상품
row. `/filters`, `/filters/tree/counts` 의 필터별 카운트가 휴지통 상품을 제외하는지
검증용.

`sample_market_registered_product` — `registered_accounts`가 채워진 상품 row. 마켓삭제
가드(휴지통이동/하드삭제 모두 공통) 실패 시나리오 테스트용 — `SambaShipmentService
.delete_from_markets`를 monkeypatch로 실패시켜, 이 상품이 실제로 트래시/삭제되지 않는지
검증하는 데 쓴다.
"""

from __future__ import annotations

from typing import AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import delete as sa_delete
from ulid import ULID

from backend.api.v1.routers.samba.collector import router as collector_router
from backend.db.orm import get_write_sessionmaker
from backend.domain.samba.collector.model import (
    SambaCollectedProduct,
    SambaSearchFilter,
)
from backend.domain.samba.tenant.middleware import get_optional_tenant_id


@pytest.fixture
def app() -> FastAPI:
    """collector 라우터만 "/samba" prefix로 마운트한 테스트 전용 앱.

    실제 서버는 "/api/v1/samba"에 마운트하지만, 여기선 브리프의 테스트 경로
    (`/samba/collector/...`)와 맞추기 위해 "/samba"만 사용한다.
    """
    test_app = FastAPI()
    test_app.include_router(collector_router, prefix="/samba")
    # get_optional_tenant_id는 JWT Authorization 헤더를 요구한다 — 라우터 단위
    # 테스트에서는 인증을 다루지 않으므로 tenant_id=None으로 override.
    test_app.dependency_overrides[get_optional_tenant_id] = lambda: None
    return test_app


@pytest.fixture
async def async_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def sample_collected_product() -> AsyncGenerator[SambaCollectedProduct, None]:
    """실제 DB에 저장된 최소 수집상품 1건. 테스트 종료 후 정리."""
    Session = get_write_sessionmaker()
    async with Session() as session:
        product = SambaCollectedProduct(
            source_site="musinsa",
            name="휴지통 테스트 상품",
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)

        yield product

        await session.execute(
            sa_delete(SambaCollectedProduct).where(
                SambaCollectedProduct.id == product.id
            )
        )
        await session.commit()


@pytest.fixture
async def sample_categorized_product() -> AsyncGenerator[SambaCollectedProduct, None]:
    """`category`가 채워진 수집상품 1건 — `/products/category-tree` 카운트 테스트용.

    카테고리값에 임의 접미사를 붙여 실제 DB에 남아있을 수 있는 다른 상품과
    겹치지 않게 한다(delta 대신 값 자체로 단언 가능).
    """
    Session = get_write_sessionmaker()
    async with Session() as session:
        product = SambaCollectedProduct(
            source_site="musinsa",
            name="휴지통 카테고리트리 테스트 상품",
            category=f"휴지통테스트카테고리_{ULID()}",
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)

        yield product

        await session.execute(
            sa_delete(SambaCollectedProduct).where(
                SambaCollectedProduct.id == product.id
            )
        )
        await session.commit()


@pytest.fixture
async def sample_filtered_product() -> AsyncGenerator[
    tuple[SambaSearchFilter, SambaCollectedProduct], None
]:
    """검색필터 1건 + 그 필터를 참조하는 수집상품 1건.

    `/filters`, `/filters/tree/counts` 의 필터별 카운트 쿼리가 휴지통 상품을
    제외하는지 검증하는 데 쓴다.
    """
    Session = get_write_sessionmaker()
    async with Session() as session:
        search_filter = SambaSearchFilter(
            source_site="musinsa", name="휴지통 필터카운트 테스트"
        )
        session.add(search_filter)
        await session.commit()
        await session.refresh(search_filter)

        product = SambaCollectedProduct(
            source_site="musinsa",
            name="휴지통 필터카운트 테스트 상품",
            search_filter_id=search_filter.id,
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)

        yield search_filter, product

        await session.execute(
            sa_delete(SambaCollectedProduct).where(
                SambaCollectedProduct.id == product.id
            )
        )
        await session.execute(
            sa_delete(SambaSearchFilter).where(SambaSearchFilter.id == search_filter.id)
        )
        await session.commit()


@pytest.fixture
async def sample_market_registered_product() -> AsyncGenerator[
    SambaCollectedProduct, None
]:
    """`registered_accounts`가 채워진(마켓등록) 상품 1건. 테스트 종료 후 정리."""
    Session = get_write_sessionmaker()
    async with Session() as session:
        product = SambaCollectedProduct(
            source_site="musinsa",
            name="마켓등록 휴지통 가드 테스트 상품",
            registered_accounts=["ma_test_account_1"],
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)

        yield product

        await session.execute(
            sa_delete(SambaCollectedProduct).where(
                SambaCollectedProduct.id == product.id
            )
        )
        await session.commit()
