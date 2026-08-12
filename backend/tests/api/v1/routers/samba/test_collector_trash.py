import pytest
from httpx import AsyncClient
from ulid import ULID

from backend.domain.samba.cache import cache


@pytest.mark.asyncio
async def test_bulk_trash_sets_deleted_at(
    async_client: AsyncClient, sample_collected_product
):
    res = await async_client.post(
        "/samba/collector/products/bulk-trash",
        json={"ids": [sample_collected_product.id]},
    )
    assert res.status_code == 200
    assert res.json()["trashed"] == 1


@pytest.mark.asyncio
async def test_trashed_product_excluded_from_scroll(
    async_client: AsyncClient, sample_collected_product
):
    await async_client.post(
        "/samba/collector/products/bulk-trash",
        json={"ids": [sample_collected_product.id]},
    )
    res = await async_client.get(
        "/samba/collector/products/scroll", params={"limit": 100}
    )
    ids = [item["id"] for item in res.json()["items"]]
    assert sample_collected_product.id not in ids


@pytest.mark.asyncio
async def test_trashed_product_excluded_from_scroll_kpi_counts(
    async_client: AsyncClient, sample_collected_product
):
    """`/products/scroll` 응답의 `counts`(KPI 타일: total/registered/policy_applied/
    sold_out)는 `items`/`total`과 별도로 구성되는 `counts_stmt`(및 소싱처 목록용
    `sites_stmt`)로 계산된다 — 이 둘도 휴지통 상품을 제외해야 한다."""
    # tenant_id 오버라이드가 None이므로 실제 캐시 키는 "...:global"
    await cache.delete("products:counts:global")
    res_before = await async_client.get(
        "/samba/collector/products/scroll", params={"limit": 100}
    )
    total_before = res_before.json()["counts"]["total"]

    await async_client.post(
        "/samba/collector/products/bulk-trash",
        json={"ids": [sample_collected_product.id]},
    )
    await cache.delete("products:counts:global")
    res_after = await async_client.get(
        "/samba/collector/products/scroll", params={"limit": 100}
    )
    total_after = res_after.json()["counts"]["total"]

    assert total_after == total_before - 1


@pytest.mark.asyncio
async def test_restore_clears_deleted_at(
    async_client: AsyncClient, sample_collected_product
):
    await async_client.post(
        "/samba/collector/products/bulk-trash",
        json={"ids": [sample_collected_product.id]},
    )
    res = await async_client.post(
        "/samba/collector/products/bulk-restore",
        json={"ids": [sample_collected_product.id]},
    )
    assert res.status_code == 200
    assert res.json()["restored"] == 1
    res2 = await async_client.get(
        "/samba/collector/products/scroll", params={"limit": 100}
    )
    ids = [item["id"] for item in res2.json()["items"]]
    assert sample_collected_product.id in ids


@pytest.mark.asyncio
async def test_bulk_trash_skips_product_when_market_delete_fails(
    async_client: AsyncClient, sample_market_registered_product, monkeypatch
):
    """마켓삭제 가드 — 마켓등록 상품은 마켓삭제 실패 시 휴지통행도 보류되어야 한다.

    bulk_delete_products(하드삭제)와 동일한 가드: delete_from_markets 결과의
    success_count가 delete_results 건수에 못 미치면 그 상품은 deleted_at을
    세팅하지 않고 market_delete_failed로 응답에 노출한다. 그렇지 않으면
    마켓엔 그대로 남아있는데 활성상품 목록/휴지통 어디에도 없는 고아상품이 된다.
    """
    from backend.domain.samba.shipment.service import SambaShipmentService

    async def _fake_delete_from_markets(
        self, product_ids, target_account_ids, *args, **kwargs
    ):
        return {
            "results": [
                {
                    "product_id": pid,
                    "success_count": 0,
                    "delete_results": {"ma_test_account_1": False},
                }
                for pid in product_ids
            ]
        }

    monkeypatch.setattr(
        SambaShipmentService, "delete_from_markets", _fake_delete_from_markets
    )

    res = await async_client.post(
        "/samba/collector/products/bulk-trash",
        json={"ids": [sample_market_registered_product.id]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["trashed"] == 0
    assert sample_market_registered_product.id in body.get("market_delete_failed", [])

    trash_res = await async_client.get("/samba/collector/products/trash")
    trashed_ids = [item["id"] for item in trash_res.json()]
    assert sample_market_registered_product.id not in trashed_ids


@pytest.mark.asyncio
async def test_trashed_product_excluded_from_counts(
    async_client: AsyncClient, sample_collected_product
):
    """`/products/counts` 의 total 카운트도 휴지통 상품을 제외해야 한다."""
    await cache.delete("products:counts")
    res_before = await async_client.get("/samba/collector/products/counts")
    total_before = res_before.json()["total"]

    await async_client.post(
        "/samba/collector/products/bulk-trash",
        json={"ids": [sample_collected_product.id]},
    )
    await cache.delete("products:counts")
    res_after = await async_client.get("/samba/collector/products/counts")
    total_after = res_after.json()["total"]

    assert total_after == total_before - 1


@pytest.mark.asyncio
async def test_trashed_product_excluded_from_dashboard_stats(
    async_client: AsyncClient, app
):
    """`/products/dashboard-stats` 의 소싱처별(musinsa) 합계도 휴지통 상품을 제외해야 한다.

    이 함수는 raw SQL로 `(:tid IS NULL OR tenant_id = :tid)`를 바인딩하는데,
    tenant_id=None(다른 테스트들의 기본 override)이면 asyncpg가 파라미터 타입을
    추론하지 못해 `AmbiguousParameterError`를 던지는 기존 버그가 있다(운영에서는
    get_optional_tenant_id의 주석대로 tenant_id가 실제로 None이 되는 경우가 없어
    드러나지 않음 — Task 3 범위 밖이라 별도로 플래그만 남김). 그래서 이 테스트는
    실제 운영처럼 tenant_id를 실제 값으로 override하고, 그 tenant에 속한 상품만
    만들어 tenant 격리로 다른 데이터와 섞이지 않게 한다.
    """
    from backend.db.orm import get_write_sessionmaker
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.tenant.middleware import get_optional_tenant_id
    from sqlmodel import delete as sa_delete

    tenant_id = f"test-tenant-dash-{ULID()}"
    app.dependency_overrides[get_optional_tenant_id] = lambda: tenant_id

    Session = get_write_sessionmaker()
    async with Session() as session:
        product = SambaCollectedProduct(
            source_site="musinsa",
            name="휴지통 대시보드 테스트 상품",
            tenant_id=tenant_id,
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)

    # [2026-08-10] 캐시 키 버전에 묶지 않는다. 이 테스트는 원래
    # `products:dashboard-stats-v5:{tid}` 를 지웠는데, 그 사이 본진이 조회 키를
    # v8 로 올려서 엉뚱한 키를 지우게 됐고 → 캐시가 안 비워져 total_before 가 0 이
    # 나왔다. 버전이 또 올라가도 안 깨지도록 패턴으로 지운다.
    async def _musinsa_total() -> int:
        await cache.clear_pattern("products:dashboard-stats-*")
        res = await async_client.get("/samba/collector/products/dashboard-stats")
        data = res.json()
        for site in data["by_source"]:
            if site["source_site"] == "musinsa":
                return site["total"]
        return 0

    try:
        total_before = await _musinsa_total()
        assert total_before == 1

        await async_client.post(
            "/samba/collector/products/bulk-trash",
            json={"ids": [product.id]},
        )

        total_after = await _musinsa_total()
        assert total_after == 0
    finally:
        Session2 = get_write_sessionmaker()
        async with Session2() as session:
            await session.execute(
                sa_delete(SambaCollectedProduct).where(
                    SambaCollectedProduct.id == product.id
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_trashed_product_excluded_from_category_tree(
    async_client: AsyncClient, sample_categorized_product
):
    """`/products/category-tree` 도 휴지통 상품을 제외해야 한다."""
    await cache.delete("products:category-tree")
    res = await async_client.get("/samba/collector/products/category-tree")
    entries = res.json()
    assert any(
        e["category"] == sample_categorized_product.category and e["count"] == 1
        for e in entries
    )

    await async_client.post(
        "/samba/collector/products/bulk-trash",
        json={"ids": [sample_categorized_product.id]},
    )
    await cache.delete("products:category-tree")
    res2 = await async_client.get("/samba/collector/products/category-tree")
    entries2 = res2.json()
    assert not any(
        e["category"] == sample_categorized_product.category for e in entries2
    )


@pytest.mark.asyncio
async def test_trashed_product_excluded_from_list_filters(
    async_client: AsyncClient, sample_filtered_product
):
    """`/filters` 의 필터별 collected_count 도 휴지통 상품을 제외해야 한다."""
    search_filter, product = sample_filtered_product

    await cache.delete("collector:filters:v2")
    res = await async_client.get("/samba/collector/filters")
    entry = next(f for f in res.json() if f["id"] == search_filter.id)
    assert entry["collected_count"] == 1

    await async_client.post(
        "/samba/collector/products/bulk-trash",
        json={"ids": [product.id]},
    )
    # bulk-trash는 collector:filters:v2 캐시를 이미 무효화한다.
    res2 = await async_client.get("/samba/collector/filters")
    entry2 = next(f for f in res2.json() if f["id"] == search_filter.id)
    assert entry2["collected_count"] == 0


@pytest.mark.asyncio
async def test_trashed_product_excluded_from_filter_tree_counts(
    async_client: AsyncClient, sample_filtered_product
):
    """`/filters/tree/counts` 의 필터별 카운트도 휴지통 상품을 제외해야 한다."""
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
