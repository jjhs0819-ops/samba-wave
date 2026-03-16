"""SambaWave Proxy API router - 외부 마켓 API 프록시.

Node.js proxy-server.mjs를 대체하는 통합 프록시 라우터.
무신사, KREAM, 롯데홈쇼핑, GS샵 외부 API를 프록시한다.

자격증명은 samba_settings 테이블에서 읽어온다:
- musinsa_cookie: 무신사 인증 쿠키
- kream_token: KREAM Bearer 토큰
- kream_cookie: KREAM 브라우저 쿠키
- lottehome_credentials: { userId, password, agncNo, env }
- gsshop_credentials: { supCd, aesKey, subSupCd, env }
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.forbidden.model import SambaSettings
from backend.domain.samba.forbidden.repository import SambaSettingsRepository
from backend.domain.samba.proxy.gsshop import GsShopApiError, GsShopClient
from backend.domain.samba.proxy.kream import KreamClient
from backend.domain.samba.proxy.lottehome import LotteApiError, LotteHomeClient
from backend.domain.samba.proxy.musinsa import MusinsaClient
from backend.utils.logger import logger

router = APIRouter(prefix="/proxy", tags=["samba-proxy"])


# ── Helper: read setting from DB ──


async def _get_setting(session: AsyncSession, key: str) -> Any:
    """samba_settings 테이블에서 설정값 조회."""
    repo = SambaSettingsRepository(session)
    row = await repo.find_by_async(key=key)
    if row:
        return row.value
    return None


async def _set_setting(session: AsyncSession, key: str, value: Any) -> None:
    """samba_settings 테이블에 설정값 저장."""
    repo = SambaSettingsRepository(session)
    existing = await repo.find_by_async(key=key)
    if existing:
        existing.value = value
        session.add(existing)
        await session.commit()
    else:
        new_row = SambaSettings(key=key, value=value)
        session.add(new_row)
        await session.commit()


async def _get_musinsa_client(session: AsyncSession) -> MusinsaClient:
    cookie = await _get_setting(session, "musinsa_cookie") or ""
    return MusinsaClient(cookie=str(cookie))


async def _get_kream_client(session: AsyncSession) -> KreamClient:
    token = await _get_setting(session, "kream_token") or ""
    cookie = await _get_setting(session, "kream_cookie") or ""
    return KreamClient(token=str(token), cookie=str(cookie))


async def _get_lotte_client(session: AsyncSession) -> LotteHomeClient:
    creds = await _get_setting(session, "lottehome_credentials") or {}
    if not isinstance(creds, dict):
        creds = {}
    return LotteHomeClient(
        user_id=creds.get("userId", ""),
        password=creds.get("password", ""),
        agnc_no=creds.get("agncNo", ""),
        env=creds.get("env", "test"),
    )


async def _get_gs_client(session: AsyncSession) -> GsShopClient:
    creds = await _get_setting(session, "gsshop_credentials") or {}
    if not isinstance(creds, dict):
        creds = {}
    return GsShopClient(
        sup_cd=creds.get("supCd", ""),
        aes_key=creds.get("aesKey", ""),
        sub_sup_cd=creds.get("subSupCd", ""),
        env=creds.get("env", "dev"),
    )


# ═══════════════════════════════════════════════
# 무신사 (Musinsa) endpoints
# ═══════════════════════════════════════════════


@router.get("/musinsa/goods/{goods_no}")
async def musinsa_goods_detail(
    goods_no: str,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """무신사 상품 상세 조회."""
    if not goods_no or not goods_no.isdigit():
        raise HTTPException(status_code=400, detail="유효하지 않은 상품번호입니다.")

    client = await _get_musinsa_client(session)
    try:
        product = await client.get_goods_detail(goods_no)
        return {"success": True, "data": product}
    except Exception as exc:
        logger.error(f"[무신사] {goods_no} 수집 실패: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/musinsa/search-api")
async def musinsa_search_api(
    keyword: str = Query("", description="검색 키워드"),
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=200),
    sort: str = Query("POPULAR"),
    category: str = Query(""),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """무신사 상품 검색 API."""
    if not keyword:
        raise HTTPException(status_code=400, detail="검색 키워드를 입력해주세요.")

    client = await _get_musinsa_client(session)
    try:
        return await client.search_products(
            keyword=keyword, page=page, size=size, sort=sort, category=category
        )
    except Exception as exc:
        logger.error(f"[무신사] 검색 실패: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/musinsa/search")
async def musinsa_search_by_url(
    url: str = Query("", description="무신사 URL"),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """URL 기반 검색/리다이렉트 처리."""
    if not url or ("musinsa.com" not in url and "musinsa.onelink.me" not in url):
        raise HTTPException(status_code=400, detail="무신사 URL을 입력해주세요.")

    client = await _get_musinsa_client(session)
    try:
        return await client.search_by_url(url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class MusinsaSetCookieRequest(BaseModel):
    cookie: str


@router.post("/musinsa/set-cookie")
async def musinsa_set_cookie(
    body: MusinsaSetCookieRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """브라우저 확장에서 쿠키 직접 전달."""
    client = MusinsaClient(cookie=body.cookie)
    result = await client.set_cookie_and_verify(body.cookie)
    # DB에 저장
    await _set_setting(write_session, "musinsa_cookie", body.cookie)
    return result


class MusinsaCheckLoginRequest(BaseModel):
    cookie: Optional[str] = None


@router.post("/musinsa/check-login")
async def musinsa_check_login(
    body: MusinsaCheckLoginRequest = MusinsaCheckLoginRequest(),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """무신사 로그인 상태 확인."""
    client = await _get_musinsa_client(session)
    return await client.check_login_status(cookie=body.cookie)


@router.get("/musinsa/auth/status")
async def musinsa_auth_status(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """무신사 인증 상태 확인."""
    cookie = await _get_setting(session, "musinsa_cookie") or ""
    return {"isLoggedIn": bool(cookie), "cookieLength": len(str(cookie))}


@router.delete("/musinsa/auth")
async def musinsa_auth_delete(
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """무신사 쿠키 초기화 (로그아웃)."""
    await _set_setting(write_session, "musinsa_cookie", "")
    return {"success": True, "isLoggedIn": False, "message": "로그아웃 완료"}


class StockCheckRequest(BaseModel):
    goodsNos: list[str]


@router.post("/musinsa/stock-check")
async def musinsa_stock_check(
    body: StockCheckRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """재고 소진 감지 (서브에이전트)."""
    if not body.goodsNos:
        raise HTTPException(status_code=400, detail="goodsNos 배열이 필요합니다.")

    client = await _get_musinsa_client(session)
    return await client.check_stock(body.goodsNos)


class PriceMonitorProduct(BaseModel):
    goodsNo: str
    storedPrice: int = 0
    productId: Optional[str] = None


class PriceMonitorRequest(BaseModel):
    products: list[PriceMonitorProduct]


@router.post("/musinsa/price-monitor")
async def musinsa_price_monitor(
    body: PriceMonitorRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """가격 변동 감지 (서브에이전트)."""
    if not body.products:
        raise HTTPException(status_code=400, detail="products 배열이 필요합니다.")

    client = await _get_musinsa_client(session)
    products_dicts = [p.model_dump() for p in body.products]
    return await client.monitor_prices(products_dicts)


# ═══════════════════════════════════════════════
# KREAM endpoints
# ═══════════════════════════════════════════════

# 확장앱 큐 (in-memory, 서버 재시작 시 초기화)
_kream_collect_queue: list[dict[str, Any]] = []
_kream_collect_resolvers: dict[str, asyncio.Future[Any]] = {}
_kream_search_queue: list[dict[str, Any]] = []
_kream_search_resolvers: dict[str, asyncio.Future[Any]] = {}


class KreamLoginRequest(BaseModel):
    email: str
    password: str


@router.post("/kream/login")
async def kream_login(
    body: KreamLoginRequest,
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
async def kream_set_cookie(
    body: KreamSetCookieRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """확장앱에서 KREAM 쿠키 수신."""
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
    if not _kream_collect_queue:
        return {"hasJob": False}
    job = _kream_collect_queue.pop(0)
    return {"hasJob": True, **job}


class KreamCollectResultRequest(BaseModel):
    requestId: str
    data: Any


@router.post("/kream/collect-result")
async def kream_collect_result(body: KreamCollectResultRequest) -> dict[str, Any]:
    """확장앱이 수집 완료 후 결과 전달."""
    future = _kream_collect_resolvers.get(body.requestId)
    if future and not future.done():
        future.set_result(body.data)
        _kream_collect_resolvers.pop(body.requestId, None)
        logger.info(f"[KREAM] 확장앱 수집 결과 수신: {body.requestId}")
    return {"success": True}


@router.get("/kream/products/{product_id}")
async def kream_product_detail(product_id: str) -> dict[str, Any]:
    """KREAM 상품 상세 조회 (확장앱 큐 방식, 최대 90초 대기)."""
    if not product_id:
        raise HTTPException(status_code=400, detail="상품 ID가 필요합니다.")

    request_id = str(uuid.uuid4())
    _kream_collect_queue.append(
        {
            "requestId": request_id,
            "productId": product_id,
            "url": f"https://kream.co.kr/products/{product_id}",
        }
    )
    logger.info(f"[KREAM] 수집 요청 큐 등록: {product_id} ({request_id})")

    loop = asyncio.get_event_loop()
    future: asyncio.Future[Any] = loop.create_future()
    _kream_collect_resolvers[request_id] = future

    try:
        result = await asyncio.wait_for(future, timeout=90.0)
        return result
    except asyncio.TimeoutError:
        _kream_collect_resolvers.pop(request_id, None)
        raise HTTPException(
            status_code=504,
            detail=(
                "수집 타임아웃. 웨일 브라우저가 열려있고 KREAM에 로그인되어 있는지 "
                "확인해주세요. 확장앱을 재활성화해 주세요."
            ),
        )


# -- 확장앱 큐 방식 (검색) --


@router.get("/kream/search-queue")
async def kream_search_queue_poll() -> dict[str, Any]:
    """확장앱이 3초마다 폴링: 대기 중인 검색 요청 가져가기."""
    if not _kream_search_queue:
        return {"hasJob": False}
    job = _kream_search_queue.pop(0)
    return {"hasJob": True, **job}


class KreamSearchResultRequest(BaseModel):
    requestId: str
    data: Any


@router.post("/kream/search-result")
async def kream_search_result(body: KreamSearchResultRequest) -> dict[str, Any]:
    """확장앱이 검색 완료 후 결과 전달."""
    future = _kream_search_resolvers.get(body.requestId)
    if future and not future.done():
        future.set_result(body.data)
        _kream_search_resolvers.pop(body.requestId, None)
        logger.info(f"[KREAM] 확장앱 검색 결과 수신: {body.requestId}")
    return {"success": True}


@router.get("/kream/search")
async def kream_search(
    keyword: str = Query("", description="검색 키워드"),
) -> dict[str, Any]:
    """KREAM 상품 검색 (확장앱 큐 방식, 최대 90초 대기)."""
    if not keyword:
        raise HTTPException(status_code=400, detail="검색 키워드를 입력해주세요.")

    from urllib.parse import quote

    search_url = f"https://kream.co.kr/search?keyword={quote(keyword)}"
    request_id = str(uuid.uuid4())

    _kream_search_queue.append(
        {"requestId": request_id, "keyword": keyword, "url": search_url}
    )
    logger.info(f'[KREAM] 검색 큐 등록: "{keyword}" ({request_id})')

    loop = asyncio.get_event_loop()
    future: asyncio.Future[Any] = loop.create_future()
    _kream_search_resolvers[request_id] = future

    try:
        result = await asyncio.wait_for(future, timeout=90.0)
        return result
    except asyncio.TimeoutError:
        _kream_search_resolvers.pop(request_id, None)
        raise HTTPException(
            status_code=504,
            detail=(
                "검색 타임아웃. 웨일 브라우저가 열려있고 KREAM에 로그인되어 있는지 "
                "확인해주세요. 확장앱을 재활성화해 주세요."
            ),
        )


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


# ═══════════════════════════════════════════════
# 롯데홈쇼핑 (Lotte Home Shopping) endpoints
# ═══════════════════════════════════════════════


class LotteAuthRequest(BaseModel):
    userId: str
    password: str
    agncNo: Optional[str] = ""
    env: Optional[str] = "test"


@router.post("/lottehome/auth")
async def lottehome_auth(
    body: LotteAuthRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 인증키 발급."""
    if not body.userId or not body.password:
        raise HTTPException(
            status_code=400, detail="협력업체ID와 비밀번호를 입력해주세요."
        )
    # DB에 자격증명 저장
    await _set_setting(
        write_session,
        "lottehome_credentials",
        {
            "userId": body.userId,
            "password": body.password,
            "agncNo": body.agncNo or "",
            "env": body.env or "test",
        },
    )
    client = LotteHomeClient(
        user_id=body.userId,
        password=body.password,
        agnc_no=body.agncNo or "",
        env=body.env or "test",
    )
    try:
        return await client.authenticate()
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}
    except Exception as exc:
        return {"success": False, "message": str(exc), "code": "AUTH_FAILED"}


@router.get("/lottehome/auth/status")
async def lottehome_auth_status(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 캐시된 인증 상태."""
    # 상태 없음 반환 (서버 인스턴스별 인증 캐시는 LotteHomeClient 인스턴스에 있으므로)
    return {"authenticated": False, "message": "인증 정보 없음 (재인증 필요)"}


@router.get("/lottehome/brands")
async def lottehome_brands(
    brnd_nm: str = Query(""),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 브랜드 목록 조회."""
    client = await _get_lotte_client(session)
    try:
        result = await client.search_brands(brnd_nm)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/lottehome/categories")
async def lottehome_categories(
    disp_tp_cd: str = Query(""),
    md_gsgr_no: str = Query(""),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 전시카테고리 목록 조회."""
    client = await _get_lotte_client(session)
    try:
        result = await client.search_categories(disp_tp_cd, md_gsgr_no)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/lottehome/md-groups")
async def lottehome_md_groups(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 MD상품군 조회."""
    client = await _get_lotte_client(session)
    try:
        result = await client.search_md_groups()
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/lottehome/delivery-policies")
async def lottehome_delivery_policies(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 배송비정책 조회."""
    client = await _get_lotte_client(session)
    try:
        result = await client.search_delivery_policies()
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/lottehome/delivery-places")
async def lottehome_delivery_places(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 배송지 조회."""
    client = await _get_lotte_client(session)
    try:
        result = await client.search_delivery_places()
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.post("/lottehome/goods")
async def lottehome_register_goods(
    goods_data: dict[str, Any],
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 신규상품등록."""
    client = await _get_lotte_client(session)
    try:
        result = await client.register_goods(goods_data)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.put("/lottehome/goods/new/{goods_req_no}")
async def lottehome_update_new_goods(
    goods_req_no: str,
    goods_data: dict[str, Any],
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 신규상품수정."""
    client = await _get_lotte_client(session)
    try:
        result = await client.update_new_goods(goods_req_no, goods_data)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.put("/lottehome/goods/display/{goods_no}")
async def lottehome_update_display_goods(
    goods_no: str,
    goods_data: dict[str, Any],
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 전시상품수정."""
    client = await _get_lotte_client(session)
    try:
        result = await client.update_display_goods(goods_no, goods_data)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


class LotteSaleStatusRequest(BaseModel):
    sale_stat_cd: str = "20"


@router.patch("/lottehome/goods/{goods_no}/status")
async def lottehome_sale_status(
    goods_no: str,
    body: LotteSaleStatusRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 판매상태 변경."""
    client = await _get_lotte_client(session)
    try:
        result = await client.update_sale_status(goods_no, body.sale_stat_cd)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


class LotteStockUpdateRequest(BaseModel):
    goods_no: str
    item_no: str
    inv_qty: int


@router.put("/lottehome/stock")
async def lottehome_update_stock(
    body: LotteStockUpdateRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 재고수정."""
    client = await _get_lotte_client(session)
    try:
        result = await client.update_stock(body.goods_no, body.item_no, body.inv_qty)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/lottehome/stock")
async def lottehome_search_stock(
    goods_no: str = Query(""),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 재고 조회."""
    client = await _get_lotte_client(session)
    try:
        result = await client.search_stock(goods_no)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


# ═══════════════════════════════════════════════
# GS샵 (GS Shop) endpoints
# ═══════════════════════════════════════════════


class GsShopCredsRequest(BaseModel):
    supCd: str
    aesKey: str
    subSupCd: Optional[str] = ""
    env: Optional[str] = "dev"


@router.post("/gsshop/auth/save")
async def gsshop_save_credentials(
    body: GsShopCredsRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """GS샵 자격증명 저장."""
    await _set_setting(
        write_session,
        "gsshop_credentials",
        {
            "supCd": body.supCd,
            "aesKey": body.aesKey,
            "subSupCd": body.subSupCd or "",
            "env": body.env or "dev",
        },
    )
    return {"success": True, "message": "GS샵 자격증명이 저장되었습니다."}


@router.get("/gsshop/auth/check")
async def gsshop_auth_check(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 인증 확인 (MDID 조회로 검증)."""
    client = await _get_gs_client(session)
    if not client.sup_cd or not client.aes_key:
        return {
            "success": False,
            "authenticated": False,
            "message": "supCd와 aesKey가 필요합니다.",
        }
    return await client.check_auth()


@router.get("/gsshop/brands")
async def gsshop_brands(
    brandNm: Optional[str] = Query(None),
    fromDtm: Optional[str] = Query(None),
    toDtm: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 브랜드 조회."""
    client = await _get_gs_client(session)
    try:
        result = await client.get_brands(
            brand_nm=brandNm, from_dtm=fromDtm, to_dtm=toDtm
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/gsshop/categories")
async def gsshop_categories(
    sectSts: str = Query("A"),
    shopAttrCd: str = Query(""),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 전시매장(카테고리) 조회."""
    client = await _get_gs_client(session)
    try:
        result = await client.get_categories(sect_sts=sectSts, shop_attr_cd=shopAttrCd)
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/gsshop/product-categories")
async def gsshop_product_categories(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 상품분류코드 전체 조회."""
    client = await _get_gs_client(session)
    try:
        result = await client.get_product_categories()
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/gsshop/delivery-places")
async def gsshop_delivery_places(
    supAddrCd: str = Query(""),
    addrGbnNm: str = Query(""),
    dirdlvRelspYn: str = Query(""),
    dirdlvRetpYn: str = Query(""),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 출고지/반송지 조회."""
    client = await _get_gs_client(session)
    try:
        result = await client.get_delivery_places(
            sup_addr_cd=supAddrCd,
            addr_gbn_nm=addrGbnNm,
            dirdlv_relsp_yn=dirdlvRelspYn,
            dirdlv_retp_yn=dirdlvRetpYn,
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/gsshop/md-list")
async def gsshop_md_list(
    subSupCheckYn: str = Query("N"),
    subSupCd: str = Query(""),
    prcModAuthYn: str = Query("A"),
    prdNmModAuthYn: str = Query("A"),
    descdModAuthYn: str = Query("A"),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 협력사 MDID 조회."""
    client = await _get_gs_client(session)
    try:
        result = await client.get_md_list(
            sub_sup_check_yn=subSupCheckYn,
            sub_sup_cd=subSupCd,
            prc_mod_auth_yn=prcModAuthYn,
            prd_nm_mod_auth_yn=prdNmModAuthYn,
            descd_mod_auth_yn=descdModAuthYn,
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.post("/gsshop/goods")
async def gsshop_register_goods(
    product_data: dict[str, Any],
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 상품 등록."""
    client = await _get_gs_client(session)
    try:
        result = await client.register_goods(product_data)
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {
            "success": False,
            "message": str(exc),
            "code": exc.code,
            "detail": exc.gs_data,
        }


@router.post("/gsshop/goods/{sup_prd_cd}/base-info")
async def gsshop_update_base_info(
    sup_prd_cd: str,
    body_data: dict[str, Any],
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 기본부가정보 수정."""
    client = await _get_gs_client(session)
    try:
        result = await client.update_goods_base_info(sup_prd_cd, body_data)
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


class GsPriceUpdateRequest(BaseModel):
    prdPrcInfo: dict[str, Any]


@router.post("/gsshop/goods/{sup_prd_cd}/price")
async def gsshop_update_price(
    sup_prd_cd: str,
    body: GsPriceUpdateRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 가격 수정."""
    client = await _get_gs_client(session)
    try:
        result = await client.update_goods_price(sup_prd_cd, body.prdPrcInfo)
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


class GsSaleStatusRequest(BaseModel):
    saleEndDtm: str
    attrSaleEndStModYn: str = "Y"


@router.post("/gsshop/goods/{sup_prd_cd}/sale-status")
async def gsshop_update_sale_status(
    sup_prd_cd: str,
    body: GsSaleStatusRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 판매상태 변경."""
    client = await _get_gs_client(session)
    try:
        result = await client.update_sale_status(
            sup_prd_cd, body.saleEndDtm, body.attrSaleEndStModYn
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


class GsImagesRequest(BaseModel):
    prdCntntListCntntUrlNm: str = ""
    mobilBannerImgUrl: str = ""


@router.post("/gsshop/goods/{sup_prd_cd}/images")
async def gsshop_update_images(
    sup_prd_cd: str,
    body: GsImagesRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 이미지 수정."""
    client = await _get_gs_client(session)
    try:
        result = await client.update_images(
            sup_prd_cd, body.prdCntntListCntntUrlNm, body.mobilBannerImgUrl
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


class GsAttributesRequest(BaseModel):
    attrPrdList: list[dict[str, Any]]
    prdTypCd: str = ""
    subSupCd: str = ""


@router.post("/gsshop/goods/{sup_prd_cd}/attributes")
async def gsshop_update_attributes(
    sup_prd_cd: str,
    body: GsAttributesRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 속성(옵션) 수정."""
    client = await _get_gs_client(session)
    try:
        result = await client.update_attributes(
            sup_prd_cd, body.attrPrdList, body.prdTypCd, body.subSupCd
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/gsshop/goods/{sup_prd_cd}/approve-status")
async def gsshop_approve_status(
    sup_prd_cd: str,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 상품 승인상태 조회."""
    client = await _get_gs_client(session)
    try:
        result = await client.get_approve_status(sup_prd_cd)
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/gsshop/goods/{sup_prd_cd}")
async def gsshop_goods_detail(
    sup_prd_cd: str,
    searchItmCd: str = Query("ALL"),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 상품 상세 조회."""
    client = await _get_gs_client(session)
    try:
        result = await client.get_goods(sup_prd_cd, search_itm_cd=searchItmCd)
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/gsshop/promotions")
async def gsshop_promotions(
    fromDtm: str = Query(""),
    toDtm: str = Query(""),
    pmoApplySt: str = Query("ALL"),
    prdCd: str = Query(""),
    prdNm: str = Query(""),
    brandCd: str = Query(""),
    rowsPerPage: int = Query(100),
    pageIdx: int = Query(1),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 프로모션 목록 조회."""
    if not fromDtm or not toDtm:
        return {
            "success": False,
            "message": "fromDtm, toDtm 필수 (yyyyMMdd, 최대 7일)",
        }
    client = await _get_gs_client(session)
    try:
        result = await client.get_promotions(
            from_dtm=fromDtm,
            to_dtm=toDtm,
            pmo_apply_st=pmoApplySt,
            prd_cd=prdCd,
            prd_nm=prdNm,
            brand_cd=brandCd,
            rows_per_page=rowsPerPage,
            page_idx=pageIdx,
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


class GsPromotionApproveRequest(BaseModel):
    saleproAgreeDocNo: str
    pmoReqNo: str
    prdCd: str
    aprvStCd: str
    aprvRetRsn: Optional[str] = ""


@router.post("/gsshop/promotions/approve")
async def gsshop_approve_promotion(
    body: GsPromotionApproveRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 프로모션 승인/반려 처리."""
    if not body.saleproAgreeDocNo or not body.pmoReqNo or not body.prdCd or not body.aprvStCd:
        return {
            "success": False,
            "message": "saleproAgreeDocNo, pmoReqNo, prdCd, aprvStCd 필수",
        }
    client = await _get_gs_client(session)
    try:
        result = await client.approve_promotion(
            salepro_agree_doc_no=body.saleproAgreeDocNo,
            pmo_req_no=body.pmoReqNo,
            prd_cd=body.prdCd,
            aprv_st_cd=body.aprvStCd,
            aprv_ret_rsn=body.aprvRetRsn or "",
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}
