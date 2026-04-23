"""소싱 관련 엔드포인트 (sourcing_queue_router 포함)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_write_session_dependency

from ._helpers import _set_setting

router = APIRouter(tags=["samba-proxy"])

# 확장앱 소싱큐 전용 라우터 — 인증 불필요 (확장앱이 토큰 없이 폴링)
sourcing_queue_router = APIRouter(prefix="/proxy", tags=["samba-proxy-public"])

EXTENSION_SITES = {
    "ABCmart",
    "GrandStage",
    "REXMONDE",
    "LOTTEON",
    "GSShop",
    "ElandMall",
    "SSF",
}


def _get_sourcing_client(site: str):
    """직접 API 클라이언트 반환."""
    s = site.lower()
    if s in ("fashionplus", "fp"):
        from backend.domain.samba.proxy.fashionplus import FashionPlusClient

        return FashionPlusClient()
    if s == "nike":
        from backend.domain.samba.proxy.nike import NikeClient

        return NikeClient()
    if s == "adidas":
        from backend.domain.samba.proxy.adidas import AdidasClient

        return AdidasClient()
    if s == "naverstore":
        from backend.domain.samba.proxy.naverstore_sourcing import (
            NaverStoreSourcingClient,
        )

        return NaverStoreSourcingClient()
    return None


class LotteonSetCookieRequest(BaseModel):
    cookie: str


@sourcing_queue_router.post("/lotteon/set-cookie")
async def lotteon_set_cookie(
    body: LotteonSetCookieRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """확장앱에서 롯데ON 쿠키 수신 (인증 불필요 — 확장앱에서 직접 호출)."""
    if not body.cookie:
        raise HTTPException(status_code=400, detail="쿠키가 필요합니다.")
    await _set_setting(write_session, "lotteon_cookie", body.cookie)
    # 메모리 캐시에도 즉시 반영
    from backend.domain.samba.proxy.lotteon_sourcing import set_lotteon_cookie
    from backend.utils.logger import logger

    set_lotteon_cookie(body.cookie)
    cookie_count = len(body.cookie.split(";"))
    logger.info(f"[LOTTEON] 확장앱에서 쿠키 수신: {cookie_count}개")
    return {"success": True, "cookieCount": cookie_count}


@sourcing_queue_router.get("/sourcing/collect-queue", response_model=None)
async def sourcing_collect_queue(request: Request) -> Any:
    """확장앱이 폴링하는 소싱 수집 큐 (인증 불필요).

    확장앱은 `X-Device-Id` 헤더로 자신의 고유 deviceId를 전달한다.
    백엔드는 오토튠 소유자 deviceId와 일치하는 작업만 해당 확장앱에 반환하므로,
    동일 사용자/테넌트의 여러 브라우저에서 중복으로 탭이 열리는 현상이 방지된다.
    """
    if getattr(request.app.state, "is_shutting_down", False):
        return JSONResponse(
            status_code=503,
            content={"hasJob": False, "shuttingDown": True},
            headers={"Connection": "close"},
        )
    from backend.domain.samba.proxy.sourcing_queue import SourcingQueue

    device_id = request.headers.get("X-Device-Id", "").strip()
    return SourcingQueue.get_next_job(device_id=device_id)


@sourcing_queue_router.post("/sourcing/collect-result")
async def sourcing_collect_result(body: dict[str, Any]) -> dict[str, Any]:
    """확장앱이 수집 결과를 전달 (인증 불필요)."""
    from backend.domain.samba.proxy.sourcing_queue import SourcingQueue

    request_id = body.get("requestId", "")
    data = body.get("data", {})
    ok = SourcingQueue.resolve_job(request_id, data)
    return {"success": ok}


@router.get("/sourcing/{site}/search")
async def sourcing_search(
    site: str,
    keyword: str = Query("", min_length=1),
    page: int = Query(1, ge=1),
) -> dict[str, Any]:
    """소싱처 통합 검색 API."""
    # 패션플러스: 직접 API
    client = _get_sourcing_client(site)
    if client:
        return await client.search(keyword, page)

    # 확장앱 기반 사이트
    if site in EXTENSION_SITES:
        from backend.domain.samba.proxy.sourcing_queue import SourcingQueue

        try:
            request_id, future = SourcingQueue.add_search_job(site, keyword)
            result = await asyncio.wait_for(future, timeout=60)
            return result
        except asyncio.TimeoutError:
            SourcingQueue.resolvers.pop(request_id, None)
            return {"products": [], "total": 0, "error": "확장앱 응답 타임아웃 (60초)"}
        except RuntimeError as e:
            return {"products": [], "total": 0, "error": str(e)}
        except Exception as e:
            return {"products": [], "total": 0, "error": str(e)}

    raise HTTPException(400, f"지원하지 않는 소싱처: {site}")


@router.get("/sourcing/{site}/detail/{product_id}")
async def sourcing_detail(
    site: str,
    product_id: str,
) -> dict[str, Any]:
    """소싱처 상품 상세 조회 API."""
    # 패션플러스: 직접 API
    client = _get_sourcing_client(site)
    if client:
        return await client.get_detail(product_id)

    # 확장앱 기반 사이트
    if site in EXTENSION_SITES:
        from backend.domain.samba.proxy.sourcing_queue import SourcingQueue

        try:
            request_id, future = SourcingQueue.add_detail_job(site, product_id)
            result = await asyncio.wait_for(future, timeout=60)
            return result
        except asyncio.TimeoutError:
            SourcingQueue.resolvers.pop(request_id, None)
            return {"error": "확장앱 응답 타임아웃 (60초)"}
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

    raise HTTPException(400, f"지원하지 않는 소싱처: {site}")
