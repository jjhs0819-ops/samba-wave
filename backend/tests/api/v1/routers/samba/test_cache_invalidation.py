"""회귀 테스트 (I2, I3) — 캐시 무효화 누락 수정 검증.

I2: `GET /collector/filters`는 60초간 `collector:filters:v2` 키로 캐시된다.
`create_filter`(필터복사), `update_filter`(이름변경/정책적용), `bulk_apply_policy`가
이 키를 무효화하지 않아 변경 후에도 최대 60초간 stale 응답이 나가던 문제 — 세 함수
모두에 `cache.delete("collector:filters:v2")`를 추가했다.

I3: `bulk_trash_products`/`bulk_restore_products`는 `collector:filters:v2`만 지우고
`products:*` 패턴(products:counts:*, products:sites:*, products:dashboard-stats-v5:*,
products:category-tree)은 지우지 않아, 하드삭제(`bulk_delete_products`)와 달리
휴지통 이동/복구 후에도 대시보드 등 캐시가 최대 30분(counts ttl=1800) stale 상태로
남던 문제 — 하드삭제와 동일하게 `cache.clear_pattern("products:*")`를 추가했다.

이 테스트들은 실제 응답 재계산 여부보다 "캐시 키가 삭제됐는가"를 직접 검증한다
(sentinel 값을 미리 넣고, 뮤테이션 호출 후 사라졌는지 확인).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from backend.domain.samba.cache import cache
from backend.domain.user.auth_service import get_user_id


@pytest.mark.asyncio
async def test_create_filter_invalidates_filters_v2_cache(
    async_client: AsyncClient, app: FastAPI
):
    app.dependency_overrides[get_user_id] = lambda: "test-user"
    await cache.set("collector:filters:v2", ["sentinel"], ttl=60)
    assert await cache.get("collector:filters:v2") == ["sentinel"]

    res = await async_client.post(
        "/samba/collector/filters",
        json={"source_site": "musinsa", "name": "I2 캐시무효화 테스트 필터"},
    )
    assert res.status_code == 201
    try:
        assert await cache.get("collector:filters:v2") is None
    finally:
        from sqlmodel import delete as sa_delete
        from backend.db.orm import get_write_sessionmaker
        from backend.domain.samba.collector.model import SambaSearchFilter

        Session = get_write_sessionmaker()
        async with Session() as session:
            await session.execute(
                sa_delete(SambaSearchFilter).where(
                    SambaSearchFilter.id == res.json()["id"]
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_update_filter_invalidates_filters_v2_cache(
    async_client: AsyncClient, sample_filtered_product
):
    search_filter, _product = sample_filtered_product
    await cache.set("collector:filters:v2", ["sentinel"], ttl=60)

    res = await async_client.put(
        f"/samba/collector/filters/{search_filter.id}",
        json={"name": "I2 캐시무효화 rename 테스트"},
    )
    assert res.status_code == 200
    assert await cache.get("collector:filters:v2") is None


@pytest.mark.asyncio
async def test_bulk_apply_policy_invalidates_filters_v2_cache(
    async_client: AsyncClient, sample_filtered_product
):
    search_filter, _product = sample_filtered_product
    await cache.set("collector:filters:v2", ["sentinel"], ttl=60)

    res = await async_client.post(
        "/samba/collector/filters/bulk-apply-policy",
        json={"filter_ids": [search_filter.id], "policy_id": "nonexistent-policy"},
    )
    assert res.status_code == 200
    assert await cache.get("collector:filters:v2") is None


@pytest.mark.asyncio
async def test_bulk_trash_clears_products_cache_pattern(
    async_client: AsyncClient, sample_collected_product
):
    await cache.set("products:counts:global", {"total": 999}, ttl=1800)
    await cache.set("products:category-tree", ["sentinel"], ttl=300)

    res = await async_client.post(
        "/samba/collector/products/bulk-trash",
        json={"ids": [sample_collected_product.id]},
    )
    assert res.status_code == 200
    assert await cache.get("products:counts:global") is None
    assert await cache.get("products:category-tree") is None


@pytest.mark.asyncio
async def test_bulk_restore_clears_products_cache_pattern(
    async_client: AsyncClient, sample_collected_product
):
    await async_client.post(
        "/samba/collector/products/bulk-trash",
        json={"ids": [sample_collected_product.id]},
    )

    await cache.set("products:counts:global", {"total": 999}, ttl=1800)
    await cache.set("products:category-tree", ["sentinel"], ttl=300)

    res = await async_client.post(
        "/samba/collector/products/bulk-restore",
        json={"ids": [sample_collected_product.id]},
    )
    assert res.status_code == 200
    assert await cache.get("products:counts:global") is None
    assert await cache.get("products:category-tree") is None
