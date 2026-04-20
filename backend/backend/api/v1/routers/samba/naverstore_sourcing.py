"""네이버스토어 소싱 API 라우터.

스마트스토어 URL 기반 상품 목록/상세 조회 엔드포인트.
(v2 — 멀티페이지 + 쿠키 기반 수집)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.domain.samba.proxy.naverstore_sourcing import NaverStoreSourcingClient

router = APIRouter(prefix="/naverstore-sourcing", tags=["NaverStore Sourcing"])


# ── DTO ──


class NaverCookiesRequest(BaseModel):
    """확장앱에서 전달받는 네이버 쿠키."""

    cookies: str = Field(..., description="브라우저 쿠키 문자열")


class ProductDetailBatchRequest(BaseModel):
    """배치 상세 조회 요청."""

    store_url: str = Field(..., description="스마트스토어 URL")
    cookies: str = Field(..., description="브라우저 쿠키 문자열")
    product_ids: list[str] = Field(
        default=[], description="상품 ID 목록 (비어있으면 목록 API에서 자동 수집)"
    )
    total_count: int = Field(40, ge=1, le=10000, description="수집할 총 상품 수")
    sort_type: str = Field("POPULAR", description="정렬")
    delay: float = Field(1.0, ge=0.3, le=5.0, description="요청 간 딜레이(초)")


# ── 스토어 정보 ──


@router.get("/store-info")
async def get_store_info(
    store_url: str = Query(
        ..., description="스마트스토어 URL (예: https://smartstore.naver.com/storename)"
    ),
) -> dict[str, Any]:
    """스토어 기본 정보 조회 (channelUid 등)."""
    client = NaverStoreSourcingClient()
    channel_uid = await client.resolve_channel_uid(store_url)
    if not channel_uid:
        raise HTTPException(
            status_code=404, detail="스토어를 찾을 수 없습니다. URL을 확인해주세요."
        )

    # URL에서 스토어명 추출
    store_name = client._extract_store_name(store_url)

    return {
        "channelUid": channel_uid,
        "storeName": store_name,
        "storeUrl": store_url,
    }


@router.get("/url-info")
async def get_url_info(
    store_url: str = Query(..., description="스마트스토어 URL"),
) -> dict[str, str]:
    """URL에서 스토어명 + 카테고리 표시명 추출 (UI 수집그룹명 생성용).

    - `/{store}/` 만 있으면 categoryName = "전체상품"
    - `/category/{id}` 이 있으면 메타 API로 카테고리 이름 조회
    - 실패 시 category_id 앞 8자 fallback
    """
    client = NaverStoreSourcingClient()
    return await client.resolve_url_info(store_url)


# ── 상품 목록 ──


@router.get("/products")
async def get_products(
    store_url: str = Query(..., description="스마트스토어 URL"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(40, ge=1, le=80, description="페이지당 상품 수"),
    sort_type: str = Query(
        "POPULAR", description="정렬 (POPULAR, RECENT, LOW_PRICE, HIGH_PRICE, REVIEW)"
    ),
) -> dict[str, Any]:
    """스토어 상품 목록 조회."""
    client = NaverStoreSourcingClient()
    result = await client.get_store_products(
        store_url,
        page=page,
        page_size=page_size,
        sort_type=sort_type,
    )

    if not result:
        raise HTTPException(status_code=404, detail="상품 목록을 가져올 수 없습니다.")

    return result


# ── 상품 상세 ──


@router.get("/product-detail")
async def get_product_detail(
    product_url: str = Query(..., description="상품 URL 또는 상품 ID"),
    channel_uid: str | None = Query(None, description="channelUid (없으면 자동 추출)"),
) -> dict[str, Any]:
    """상품 상세 조회 (쿠키 없이 — 목록 수준 데이터만 반환될 수 있음)."""
    client = NaverStoreSourcingClient()
    detail = await client.get_product_detail(product_url, channel_uid=channel_uid)

    if not detail:
        raise HTTPException(status_code=404, detail="상품 정보를 가져올 수 없습니다.")

    return detail


# ── 쿠키 기반 상세 조회 (확장앱 연동) ──


@router.post("/product-detail")
async def get_product_detail_with_cookies(
    product_url: str = Query(..., description="상품 URL 또는 상품 ID"),
    body: NaverCookiesRequest = ...,
    channel_uid: str | None = Query(None, description="channelUid (없으면 자동 추출)"),
) -> dict[str, Any]:
    """상품 상세 조회 — 확장앱 쿠키 포함 (옵션/재고 완전 데이터)."""
    client = NaverStoreSourcingClient()
    detail = await client.get_product_detail(
        product_url, channel_uid=channel_uid, cookies=body.cookies
    )

    if not detail:
        raise HTTPException(status_code=404, detail="상품 정보를 가져올 수 없습니다.")

    return detail


@router.post("/product-details-batch")
async def get_product_details_batch(
    body: ProductDetailBatchRequest,
) -> dict[str, Any]:
    """상품 배치 상세 조회 — 목록 수집 + 쿠키 기반 상세 조회 일괄 처리.

    1. store_url로 목록 API 호출 (curl_cffi, 쿠키 불필요)
    2. product_ids가 없으면 목록에서 자동 추출
    3. 각 상품에 대해 쿠키 포함 상세 API 호출
    4. 목록 + 상세 데이터 병합하여 반환
    """
    client = NaverStoreSourcingClient()

    # 1단계: 멀티페이지 목록 수집 (쿠키 포함 — 2페이지부터 쿠키 필요)
    list_result = await client.get_store_products_multi(
        store_url=body.store_url,
        total_count=body.total_count,
        page_size=40,
        sort_type=body.sort_type,
        page_delay=body.delay,
        cookies=body.cookies,
    )

    all_products = list_result.get("products", [])
    channel_uid = list_result.get("channelUid", "")
    total_in_store = list_result.get("totalCount", 0)
    store_name = list_result.get("storeName", "")

    if not all_products:
        raise HTTPException(status_code=404, detail="상품 목록을 가져올 수 없습니다.")

    # 2단계: 상세 조회할 상품 ID 결정
    target_ids = body.product_ids
    if not target_ids:
        target_ids = [
            p["siteProductId"] for p in all_products if p.get("siteProductId")
        ]

    # 3단계: 쿠키 기반 배치 상세 조회
    details = await client.get_product_details_batch(
        product_ids=target_ids,
        channel_uid=channel_uid,
        delay=body.delay,
        cookies=body.cookies,
    )

    # 4단계: 상세 데이터를 ID 기준으로 매핑
    detail_map = {d["siteProductId"]: d for d in details if d.get("siteProductId")}

    # 목록 데이터에 상세 데이터 병합
    merged = []
    for lp in all_products:
        pid = lp.get("siteProductId", "")
        detail = detail_map.get(pid)
        if detail:
            merged.append(detail)
        else:
            merged.append(lp)

    return {
        "products": merged,
        "totalCount": total_in_store,
        "fetchedCount": len(all_products),
        "channelUid": channel_uid,
        "storeName": store_name,
        "detailFetched": len(details),
        "detailTotal": len(target_ids),
    }
