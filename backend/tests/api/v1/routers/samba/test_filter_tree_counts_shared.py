"""회귀 테스트 (I1) — `/filters/tree/counts` 엔드포인트와 `lifecycle.py` 캐시 워머가
공유하는 `build_filter_tree_counts_stmt`가 휴지통 상품을 제외하는지 검증.

배경: 워머가 엔드포인트의 집계 쿼리를 따로 복제해 구현하다 `deleted_at IS NULL`
조건을 빠뜨려 캐시가 휴지통 상품을 다시 카운트에 포함시키는 사고(I1)가 있었다.
수정은 두 호출부가 `collector_common.build_filter_tree_counts_stmt`라는 단일 함수를
공유하도록 만드는 것 — 이 테스트는 그 공유 함수 자체가 deleted_at 필터를 갖고
있는지, 그리고 엔드포인트가 실제로 이를 통해 휴지통 상품을 제외하는지 검증한다.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from backend.api.v1.routers.samba.collector_common import build_filter_tree_counts_stmt
from backend.domain.samba.cache import cache
from backend.domain.samba.collector.model import SambaCollectedProduct


@pytest.mark.asyncio
async def test_build_filter_tree_counts_stmt_excludes_trashed(db_session):
    """공유 집계 함수 자체가 deleted_at IS NULL 조건을 갖고 있는지 직접 검증."""
    stmt = build_filter_tree_counts_stmt(SambaCollectedProduct, ["some-filter-id"])
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "deleted_at" in compiled


@pytest.mark.asyncio
async def test_filter_tree_counts_endpoint_excludes_trashed(
    async_client: AsyncClient, sample_filtered_product
):
    """`/filters/tree/counts` 응답이 휴지통 상품을 카운트에서 제외해야 한다
    (공유 함수를 통한 엔드포인트 동작 검증 — 워머 자체는 서버 시작시에만 실행되어
    라우터 테스트 범위에서 직접 호출하기 어려우므로, 동일 공유 함수를 쓰는
    엔드포인트로 대리 검증한다)."""
    search_filter, product = sample_filtered_product
    cache_key = "filters:tree:counts:__all__"

    await cache.delete(cache_key)
    res = await async_client.get("/samba/collector/filters/tree/counts")
    counts = res.json()
    assert counts[search_filter.id]["collected_count"] == 1

    await async_client.post(
        "/samba/collector/products/bulk-trash",
        json={"ids": [product.id]},
    )
    await cache.delete(cache_key)
    res2 = await async_client.get("/samba/collector/filters/tree/counts")
    counts2 = res2.json()
    assert search_filter.id not in counts2
