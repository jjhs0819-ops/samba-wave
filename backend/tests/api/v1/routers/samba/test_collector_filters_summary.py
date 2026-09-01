"""`GET /collector/filters` 응답에 필터별 누적매출(`revenue_sum`)·휴지통 개수
(`trashed_count`)가 포함되는지 검증.

`sample_filter`/`sample_collected_product`/`sample_order`/`cancelled_order` 는 이
파일 전용 로컬 fixture다 (conftest.py의 `sample_collected_product`는 필터에
연결되지 않은 독립 상품이라 이 테스트 목적에 맞지 않아, 같은 이름으로 로컬
오버라이드한다 — pytest는 테스트 모듈에 정의된 fixture를 conftest보다 우선한다).
"""

from __future__ import annotations

from typing import AsyncGenerator

import pytest
from httpx import AsyncClient
from sqlmodel import delete as sa_delete

from backend.db.orm import get_write_sessionmaker
from backend.domain.samba.cache import cache
from backend.domain.samba.collector.model import (
    SambaCollectedProduct,
    SambaSearchFilter,
)
from backend.domain.samba.order.model import SambaOrder


@pytest.fixture
async def sample_filter() -> AsyncGenerator[SambaSearchFilter, None]:
    Session = get_write_sessionmaker()
    async with Session() as session:
        search_filter = SambaSearchFilter(
            source_site="musinsa", name="필터요약 테스트 필터"
        )
        session.add(search_filter)
        await session.commit()
        await session.refresh(search_filter)

        yield search_filter

        await session.execute(
            sa_delete(SambaSearchFilter).where(SambaSearchFilter.id == search_filter.id)
        )
        await session.commit()


@pytest.fixture
async def sample_collected_product(
    sample_filter: SambaSearchFilter,
) -> AsyncGenerator[SambaCollectedProduct, None]:
    Session = get_write_sessionmaker()
    async with Session() as session:
        product = SambaCollectedProduct(
            source_site="musinsa",
            name="필터요약 테스트 상품",
            search_filter_id=sample_filter.id,
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
async def sample_order(
    sample_collected_product: SambaCollectedProduct,
) -> AsyncGenerator[SambaOrder, None]:
    Session = get_write_sessionmaker()
    async with Session() as session:
        order = SambaOrder(
            collected_product_id=sample_collected_product.id,
            status="pending",
            sale_price=12345.0,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        yield order

        await session.execute(sa_delete(SambaOrder).where(SambaOrder.id == order.id))
        await session.commit()


@pytest.fixture
async def cancelled_order(
    sample_collected_product: SambaCollectedProduct,
) -> AsyncGenerator[SambaOrder, None]:
    Session = get_write_sessionmaker()
    async with Session() as session:
        order = SambaOrder(
            collected_product_id=sample_collected_product.id,
            status="cancelled",
            sale_price=99999.0,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        yield order

        await session.execute(sa_delete(SambaOrder).where(SambaOrder.id == order.id))
        await session.commit()


@pytest.mark.asyncio
async def test_filters_list_includes_revenue_and_trashed(
    async_client: AsyncClient,
    sample_filter,
    sample_collected_product,
    sample_order,
):
    await cache.delete("collector:filters:v2")
    res = await async_client.get("/samba/collector/filters")
    assert res.status_code == 200
    row = next(f for f in res.json() if f["id"] == sample_filter.id)
    assert "revenue_sum" in row
    assert "trashed_count" in row
    assert row["revenue_sum"] == sample_order.sale_price
    assert row["trashed_count"] == 0


@pytest.mark.asyncio
async def test_cancelled_order_excluded_from_revenue(
    async_client: AsyncClient,
    sample_filter,
    sample_collected_product,
    cancelled_order,
):
    await cache.delete("collector:filters:v2")
    res = await async_client.get("/samba/collector/filters")
    row = next(f for f in res.json() if f["id"] == sample_filter.id)
    assert row["revenue_sum"] == 0


@pytest.mark.asyncio
async def test_trashed_product_counted_in_trashed_count(
    async_client: AsyncClient,
    sample_filter,
    sample_collected_product,
):
    await cache.delete("collector:filters:v2")
    await async_client.post(
        "/samba/collector/products/bulk-trash",
        json={"ids": [sample_collected_product.id]},
    )
    res = await async_client.get("/samba/collector/filters")
    row = next(f for f in res.json() if f["id"] == sample_filter.id)
    assert row["trashed_count"] == 1
