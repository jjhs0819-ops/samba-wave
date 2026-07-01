"""KREAM 관련 엔드포인트."""

from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from backend.core.rate_limit import RATE_LOGIN, RATE_SET_COOKIE, limiter
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.proxy.kream import KreamClient
from backend.shutdown_state import is_shutting_down
from backend.utils.logger import logger

from ._helpers import _get_kream_client, _set_setting

router = APIRouter(tags=["samba-proxy"])

# 확장앱 큐: KreamClient 클래스 레벨 큐 사용 (collector.py와 공유)
# KreamClient.collect_queue, KreamClient.collect_resolvers
# KreamClient.search_queue, KreamClient.search_resolvers


class KreamLoginRequest(BaseModel):
    email: str
    password: str


@router.post("/kream/login")
@limiter.limit(RATE_LOGIN)
async def kream_login(
    request: Request,
    body: KreamLoginRequest = Body(...),
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """KREAM 로그인."""
    client = KreamClient()
    result = await client.login(body.email, body.password)
    if result.get("success") and client.token:
        await _set_setting(write_session, "kream_token", client.token)
    return result


@router.get("/kream/auth/status")
async def kream_auth_status(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """KREAM 인증 상태 확인."""
    client = await _get_kream_client(session)
    return await client.check_auth_status()


@router.delete("/kream/auth")
async def kream_auth_delete(
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """KREAM 로그아웃."""
    await _set_setting(write_session, "kream_token", "")
    await _set_setting(write_session, "kream_cookie", "")
    return {"success": True, "message": "KREAM 로그아웃 완료"}


class KreamSetTokenRequest(BaseModel):
    token: str
    userId: Optional[str] = None


@router.post("/kream/set-token")
async def kream_set_token(
    body: KreamSetTokenRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """KREAM 토큰 직접 설정."""
    if not body.token:
        raise HTTPException(status_code=400, detail="토큰을 입력해주세요.")
    await _set_setting(write_session, "kream_token", body.token)
    return {"success": True, "message": "토큰이 설정되었습니다."}


class KreamSetCookieRequest(BaseModel):
    cookie: str


@router.post("/kream/set-cookie")
@limiter.limit(RATE_SET_COOKIE)
async def kream_set_cookie(
    request: Request,
    body: KreamSetCookieRequest = Body(...),
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """확장앱에서 KREAM 쿠키 수신.

    (2026-05-20) owner_device_ids 가드 적용 — 포크 확장앱 미러 전송 차단.
    """
    from backend.api.v1.routers.samba.sourcing_account import _check_owner_device

    _check_owner_device(request)

    if not body.cookie:
        raise HTTPException(status_code=400, detail="쿠키가 필요합니다.")
    await _set_setting(write_session, "kream_cookie", body.cookie)
    cookie_count = len(body.cookie.split(";"))
    logger.info(f"[KREAM] 확장앱에서 쿠키 수신: {cookie_count}개")
    return {"success": True, "cookieCount": cookie_count}


# -- 확장앱 큐 방식 (수집) --


@router.get("/kream/collect-queue")
async def kream_collect_queue_poll() -> dict[str, Any]:
    """확장앱이 폴링: 대기 중인 수집 요청 가져가기."""
    if is_shutting_down():
        return {"hasJob": False, "shuttingDown": True}
    if not KreamClient.collect_queue:
        return {"hasJob": False}
    job = KreamClient.collect_queue.pop(0)
    return {"hasJob": True, **job}


class KreamCollectResultRequest(BaseModel):
    requestId: str
    data: Any


@router.post("/kream/collect-result")
async def kream_collect_result(body: KreamCollectResultRequest) -> dict[str, Any]:
    """확장앱이 수집 완료 후 결과 전달."""
    future = KreamClient.collect_resolvers.get(body.requestId)
    if future and not future.done():
        future.set_result(body.data)
        KreamClient.collect_resolvers.pop(body.requestId, None)
        logger.info(f"[KREAM] 확장앱 수집 결과 수신: {body.requestId}")
    return {"success": True}


@router.get("/kream/products/{product_id}")
async def kream_product_detail(product_id: str) -> dict[str, Any]:
    """KREAM 상품 상세 조회 (확장앱 큐 방식, 최대 90초 대기)."""
    if not product_id:
        raise HTTPException(status_code=400, detail="상품 ID가 필요합니다.")

    client = KreamClient()
    try:
        return await client.get_product(product_id)
    except Exception as exc:
        raise HTTPException(status_code=504, detail=str(exc))


# -- 확장앱 큐 방식 (검색) --


@router.get("/kream/search-queue")
async def kream_search_queue_poll() -> dict[str, Any]:
    """확장앱이 3초마다 폴링: 대기 중인 검색 요청 가져가기."""
    if is_shutting_down():
        return {"hasJob": False, "shuttingDown": True}
    if not KreamClient.search_queue:
        return {"hasJob": False}
    job = KreamClient.search_queue.pop(0)
    return {"hasJob": True, **job}


class KreamSearchResultRequest(BaseModel):
    requestId: str
    data: Any


@router.post("/kream/search-result")
async def kream_search_result(body: KreamSearchResultRequest) -> dict[str, Any]:
    """확장앱이 검색 완료 후 결과 전달."""
    future = KreamClient.search_resolvers.get(body.requestId)
    if future and not future.done():
        future.set_result(body.data)
        KreamClient.search_resolvers.pop(body.requestId, None)
        logger.info(f"[KREAM] 확장앱 검색 결과 수신: {body.requestId}")
    return {"success": True}


@router.get("/kream/search")
async def kream_search(
    keyword: str = Query("", description="검색 키워드"),
) -> dict[str, Any]:
    """KREAM 상품 검색 (확장앱 큐 방식, 최대 90초 대기)."""
    if not keyword:
        raise HTTPException(status_code=400, detail="검색 키워드를 입력해주세요.")

    client = KreamClient()
    try:
        items = await client.search(keyword)
        return {"success": True, "data": items}
    except Exception as exc:
        raise HTTPException(status_code=504, detail=str(exc))


@router.get("/kream/products/{product_id}/prices")
async def kream_product_prices(
    product_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """KREAM 사이즈별 시세 조회."""
    client = await _get_kream_client(session)
    result = await client.get_prices(product_id)
    if not result.get("success"):
        status = 401 if "쿠키" in result.get("message", "") else 500
        raise HTTPException(status_code=status, detail=result.get("message"))
    return result


class KreamSellBidRequest(BaseModel):
    productId: str
    size: str
    price: int
    saleType: str = "general"


@router.post("/kream/sell/bid")
async def kream_sell_bid(
    body: KreamSellBidRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """KREAM 매도 입찰 등록."""
    client = await _get_kream_client(session)
    if not client.token:
        raise HTTPException(status_code=401, detail="KREAM 로그인이 필요합니다.")

    result = await client.create_ask(
        product_id=body.productId,
        size=body.size,
        price=body.price,
        sale_type=body.saleType,
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=400, detail=result.get("message", "매도 입찰 실패")
        )
    return result


class KreamUpdateBidRequest(BaseModel):
    price: int


@router.put("/kream/sell/bid/{ask_id}")
async def kream_update_bid(
    ask_id: str,
    body: KreamUpdateBidRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """KREAM 매도 입찰 수정."""
    client = await _get_kream_client(session)
    return await client.update_ask(ask_id, body.price)


@router.delete("/kream/sell/bid/{ask_id}")
async def kream_cancel_bid(
    ask_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """KREAM 매도 입찰 취소."""
    client = await _get_kream_client(session)
    return await client.cancel_ask(ask_id)


@router.get("/kream/sell/my-bids")
async def kream_my_bids(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """KREAM 내 매도 입찰 목록."""
    client = await _get_kream_client(session)
    if not client.token:
        raise HTTPException(status_code=401, detail="KREAM 로그인이 필요합니다.")
    return await client.get_my_asks()


# 입찰 중인 크림 상품번호 제외 목록
_BID_EXCLUDE_IDS = {
    "647550",
    "647566",
    "647571",
    "647572",
    "647660",
    "648666",
    "649207",
    "649343",
    "649345",
    "649348",
    "649349",
    "649352",
    "649354",
    "649355",
    "649360",
    "649367",
    "649502",
    "649919",
    "649931",
    "650609",
    "650611",
    "651028",
    "651052",
    "651302",
    "651309",
    "651409",
    "651473",
    "651517",
    "651521",
    "651523",
    "651551",
    "652139",
    "652197",
    "652293",
    "652309",
    "652319",
    "652339",
    "652680",
    "652706",
    "652713",
    "652717",
    "652722",
    "652730",
    "652868",
    "653134",
    "653275",
    "653373",
    "653374",
    "653813",
    "654148",
    "654164",
    "654166",
    "654275",
    "654285",
    "656392",
    "656460",
    "656517",
    "656530",
    "657236",
    "657546",
    "657553",
    "657564",
    "660679",
    "660881",
    "662562",
    "662757",
    "667591",
    "667683",
    "667796",
    "668209",
    "670152",
    "670201",
    "670245",
    "670269",
    "670276",
    "670287",
    "670302",
    "70056",
    "70058",
    "70140",
    "70141",
    "70145",
    "70153",
    "70163",
    "70168",
    "70173",
    "726943",
    "728970",
    "754351",
    "754384",
    "803225",
    "809373",
    "809391",
    "809401",
    "831248",
    "831275",
    "842194",
    "845571",
    "845577",
    "845588",
    "873214",
    "873239",
    "873246",
    "920139",
}

# 크림 상품 정보 메모리 캐시
_kream_info_cache: dict[str, dict] = {}


@router.get("/kream/snkrdunk-compare")
async def snkrdunk_kream_compare(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """스니덩크-크림 매칭 상품 비교 목록 (오매칭 검수용)."""
    import asyncio
    import json
    from sqlalchemy import text

    offset = (page - 1) * per_page
    exclude_list = list(_BID_EXCLUDE_IDS)

    count_sql = text("""
        SELECT COUNT(*) FROM samba_collected_product
        WHERE source_site = 'SNKRDUNK'
        AND resell_matches->'kream'->>'product_id' IS NOT NULL
        AND NOT (resell_matches->'kream'->>'product_id' = ANY(:excl))
        AND EXISTS (
            SELECT 1 FROM jsonb_array_elements(options::jsonb) opt
            WHERE opt->>'name' ILIKE '%PSA 10%'
            AND (opt->>'stock')::int > 0
        )
    """)
    total_row = await session.exec(count_sql.bindparams(excl=exclude_list))  # type: ignore[arg-type]
    total = total_row.scalar()

    rows_sql = text("""
        SELECT site_product_id, name, images,
               resell_matches->'kream'->>'product_id' AS kream_id,
               options
        FROM samba_collected_product
        WHERE source_site = 'SNKRDUNK'
        AND resell_matches->'kream'->>'product_id' IS NOT NULL
        AND NOT (resell_matches->'kream'->>'product_id' = ANY(:excl))
        AND EXISTS (
            SELECT 1 FROM jsonb_array_elements(options::jsonb) opt
            WHERE opt->>'name' ILIKE '%PSA 10%'
            AND (opt->>'stock')::int > 0
        )
        ORDER BY site_product_id
        LIMIT :lim OFFSET :off
    """)
    result = await session.exec(
        rows_sql.bindparams(excl=exclude_list, lim=per_page, off=offset)
    )  # type: ignore[arg-type]
    rows = result.fetchall()

    # 크림 정보 병렬 조회 (캐시 활용)
    kream_client = KreamClient()
    uncached = [r.kream_id for r in rows if r.kream_id not in _kream_info_cache]

    async def _fetch_kream(kid: str) -> None:
        try:
            info = await kream_client.get_product(kid)
            _kream_info_cache[kid] = info
        except Exception:
            _kream_info_cache[kid] = {"name": "", "images": []}

    if uncached:
        await asyncio.gather(*[_fetch_kream(kid) for kid in uncached])

    items = []
    for r in rows:
        images = json.loads(r.images) if r.images else []
        opts = json.loads(r.options) if r.options else []
        psa_opts = [o for o in opts if "PSA 10" in (o.get("name") or "")]
        kinfo = _kream_info_cache.get(r.kream_id, {})
        items.append(
            {
                "snkr_id": r.site_product_id,
                "snkr_name": r.name or "",
                "snkr_image": images[0] if images else "",
                "kream_id": r.kream_id,
                "kream_name": kinfo.get("name", ""),
                "kream_image": kinfo.get("images", [""])[0]
                if kinfo.get("images")
                else "",
                "psa10_price": psa_opts[0].get("price", 0) if psa_opts else 0,
                "psa10_stock": psa_opts[0].get("stock", 0) if psa_opts else 0,
            }
        )

    return {"total": total, "page": page, "per_page": per_page, "items": items}


@router.delete("/kream/snkrdunk-compare/{snkr_id}/match")
async def snkrdunk_remove_match(
    snkr_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """스니덩크 상품의 크림 매칭 해제."""
    from sqlalchemy import text

    sql = text("""
        UPDATE samba_collected_product
        SET resell_matches = resell_matches - 'kream', updated_at = NOW()
        WHERE source_site = 'SNKRDUNK' AND site_product_id = :sid
    """)
    await session.exec(sql.bindparams(sid=snkr_id))  # type: ignore[arg-type]
    await session.commit()
    # 캐시 무효화 불필요 (snkr_id 기준)
    return {"ok": True}


@router.get("/kream/image-proxy")
async def kream_image_proxy(
    url: str = Query("", description="이미지 URL"),
) -> Response:
    """이미지 프록시 (KREAM 이미지 CORS 우회)."""
    if not url:
        raise HTTPException(status_code=400, detail="URL 필요")
    try:
        from urllib.parse import unquote

        image_bytes, content_type = await KreamClient.proxy_image(unquote(url))
        return Response(
            content=image_bytes,
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=86400",
                "Access-Control-Allow-Origin": "*",
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
