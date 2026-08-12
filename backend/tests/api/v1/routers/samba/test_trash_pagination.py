"""회귀 테스트 (I6) — `GET /products/trash`가 다른 목록 엔드포인트와 동일하게
경량 필드 프로젝션 + limit/skip 페이지네이션을 갖는지 검증.

배경: `list_trashed_products`는 이 파일의 다른 목록 엔드포인트(scroll_products,
get_products_by_ids 등)와 달리 select(_CP) 전체 컬럼을 무제한으로 반환하는
유일한 목록 엔드포인트였다 — 휴지통이 커지면 무거운 필드(detail_html 등)까지
전부 실어 보내는 문제. `_HEAVY_FIELDS` 제외 + `limit`(기본 200, 최대 1000)/
`skip` 파라미터를 추가했다.
"""

from __future__ import annotations

from typing import AsyncGenerator

import pytest
from httpx import AsyncClient
from sqlmodel import delete as sa_delete
from ulid import ULID

from backend.db.orm import get_write_sessionmaker
from backend.domain.samba.collector.model import SambaCollectedProduct


@pytest.fixture
async def sample_trashed_products() -> AsyncGenerator[
    list[SambaCollectedProduct], None
]:
    """휴지통 페이지네이션 테스트용 — 무거운 필드(detail_html)를 채운 휴지통 상품 3건."""
    from datetime import datetime, timezone

    tag = f"휴지통페이지네이션테스트_{ULID()}"
    Session = get_write_sessionmaker()
    async with Session() as session:
        products = [
            SambaCollectedProduct(
                source_site="musinsa",
                name=f"{tag}_{i}",
                deleted_at=datetime.now(timezone.utc),
                detail_html="<div>매우 무거운 상세 HTML</div>" * 100,
            )
            for i in range(3)
        ]
        for p in products:
            session.add(p)
        await session.commit()
        for p in products:
            await session.refresh(p)

        yield products

        await session.execute(
            sa_delete(SambaCollectedProduct).where(
                SambaCollectedProduct.id.in_([p.id for p in products])
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_trash_list_excludes_heavy_fields(
    async_client: AsyncClient, sample_trashed_products
):
    res = await async_client.get(
        "/samba/collector/products/trash", params={"limit": 100}
    )
    assert res.status_code == 200
    ids = {p.id for p in sample_trashed_products}
    rows = [r for r in res.json() if r["id"] in ids]
    assert len(rows) == 3
    for row in rows:
        assert "detail_html" not in row
        assert "price_history" not in row
        assert "extra_data" not in row


@pytest.mark.asyncio
async def test_trash_list_respects_limit_and_skip(
    async_client: AsyncClient, sample_trashed_products
):
    ids = {p.id for p in sample_trashed_products}

    res_page1 = await async_client.get(
        "/samba/collector/products/trash", params={"limit": 2, "skip": 0}
    )
    assert res_page1.status_code == 200
    assert len(res_page1.json()) <= 2

    res_all = await async_client.get(
        "/samba/collector/products/trash", params={"limit": 1000, "skip": 0}
    )
    matched_all = [r for r in res_all.json() if r["id"] in ids]
    assert len(matched_all) == 3


@pytest.mark.asyncio
async def test_trash_list_limit_capped_at_1000(async_client: AsyncClient):
    res = await async_client.get(
        "/samba/collector/products/trash", params={"limit": 5000}
    )
    assert res.status_code == 422
