"""번개장터 확장앱 검색 큐 엔드포인트."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.domain.samba.proxy.bunjang import BunjangClient
from backend.shutdown_state import is_shutting_down
from backend.utils.logger import logger

# 확장앱 폴링 전용 — 인증 불필요(JWT 미소지). kream.router처럼 인증 라우터에 얹으면
# 확장앱 폴링이 401로 막힘(실제 KREAM 큐도 같은 이유로 폴링 루프에서 비활성화된 전례).
bunjang_queue_router = APIRouter(prefix="/proxy", tags=["samba-proxy-public"])

# 확장앱 큐: BunjangClient 클래스 레벨 큐 사용
# BunjangClient.search_queue, BunjangClient.search_resolvers


@bunjang_queue_router.get("/bunjang/search-queue")
async def bunjang_search_queue_poll() -> dict[str, Any]:
    """확장앱이 폴링: 대기 중인 검색 요청 가져가기."""
    if is_shutting_down():
        return {"hasJob": False, "shuttingDown": True}
    if not BunjangClient.search_queue:
        return {"hasJob": False}
    job = BunjangClient.search_queue.pop(0)
    return {"hasJob": True, **job}


class BunjangSearchResultRequest(BaseModel):
    requestId: str
    data: Any


@bunjang_queue_router.post("/bunjang/search-result")
async def bunjang_search_result(body: BunjangSearchResultRequest) -> dict[str, Any]:
    """확장앱이 검색 완료 후 결과 전달."""
    future = BunjangClient.search_resolvers.get(body.requestId)
    if future and not future.done():
        future.set_result(body.data)
        BunjangClient.search_resolvers.pop(body.requestId, None)
        logger.info(f"[번개장터] 확장앱 검색 결과 수신: {body.requestId}")
    return {"success": True}


@bunjang_queue_router.get("/bunjang/search")
async def bunjang_search(
    keyword: str,
    brand_id: str = "",
    min_price: int = 0,
    max_price: int = 0,
    condition: str = "",
    min_seller_sales: int = 0,
    min_seller_rating: float = 0.0,
    limit: int = 10,
) -> dict[str, Any]:
    """번개장터 키워드 검색 (확장앱 큐 경유) — 판매자 신뢰도 필터 지원."""
    from backend.domain.samba.plugins.sourcing.bunjang import BunjangPlugin

    plugin = BunjangPlugin()
    items = await plugin.search(
        keyword,
        brand_id=brand_id,
        min_price=min_price,
        max_price=max_price,
        condition=condition,
        min_seller_sales=min_seller_sales or None,
        min_seller_rating=min_seller_rating or None,
        limit=limit,
    )
    return {"items": items, "count": len(items)}
