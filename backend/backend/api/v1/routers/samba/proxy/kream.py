"""KREAM 관련 엔드포인트."""

from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from backend.core.rate_limit import RATE_LOGIN, RATE_SET_COOKIE, limiter
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.proxy.kream import KreamClient
from backend.shutdown_state import is_shutting_down
from backend.utils.logger import logger

from ._helpers import _get_kream_client, _set_setting

router = APIRouter(tags=["samba-proxy"])

# 인증 없는 로컬 전용 라우터 (snkrdunk 매칭 수정)
snkrdunk_public_router = APIRouter(tags=["kream-public"])

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
               resell_matches->'kream'->>'image' AS kream_image_db,
               resell_matches->'kream'->>'name_en' AS kream_name_en_db,
               resell_matches->'kream'->>'name_ko' AS kream_name_ko_db,
               resell_matches->'kream'->>'style_code' AS kream_style_code_db,
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
                "kream_image": r.kream_image_db
                or (kinfo.get("images", [""])[0] if kinfo.get("images") else ""),
                "psa10_price": psa_opts[0].get("price", 0) if psa_opts else 0,
                "psa10_stock": psa_opts[0].get("stock", 0) if psa_opts else 0,
                "kream_name_en": r.kream_name_en_db or "",
                "kream_name_ko": r.kream_name_ko_db or "",
                "kream_style_code": r.kream_style_code_db or "",
            }
        )

    return {"total": total, "page": page, "per_page": per_page, "items": items}


async def _snkrdunk_remove_match_impl(
    snkr_id: str, session: AsyncSession
) -> dict[str, Any]:
    from sqlalchemy import text

    sql = text("""
        UPDATE samba_collected_product
        SET resell_matches = resell_matches - 'kream', updated_at = NOW()
        WHERE source_site = 'SNKRDUNK' AND site_product_id = :sid
    """)
    await session.exec(sql.bindparams(sid=snkr_id))  # type: ignore[arg-type]
    await session.commit()
    return {"ok": True}


async def _snkrdunk_update_match_impl(
    snkr_id: str,
    kream_id: str,
    session: AsyncSession,
    kream_name_ko: str = "",
    style_code: str = "",
) -> dict[str, Any]:
    from sqlalchemy import text

    # 크림 API로 이미지 조회 (캐시 우선). 이름은 자동으로 덮어쓰지 않는다
    # — 사용자가 검수툴에서 직접 저장한 한글명을 링크 교정이 지우는 버그 방지.
    kream_image = ""
    try:
        kream_client = KreamClient()
        if kream_id not in _kream_info_cache:
            info = await kream_client.get_product(kream_id)
            _kream_info_cache[kream_id] = info
        kinfo = _kream_info_cache.get(kream_id, {})
        kream_image = kinfo.get("images", [""])[0] if kinfo.get("images") else ""
    except Exception:
        pass

    # merge 방식: 기존 kream 객체(style_code/image 등)를 보존하고
    # product_id 와 명시적으로 넘어온 값만 덮어쓴다. `||`는 우측 우선이라
    # 기존 키는 유지된다. 링크 교정이 품번/이미지를 날리는 사고 방지.
    override_parts = ["'product_id', CAST(:kream_id AS text)"]
    if style_code:
        override_parts.append("'style_code', CAST(:style_code AS text)")
    if kream_image:
        override_parts.append("'image', CAST(:kream_image AS text)")
    override_obj = "jsonb_build_object(" + ", ".join(override_parts) + ")"

    # 한글명(name)은 caller가 kream_name_ko를 명시했을 때만 갱신
    name_set = ", name = :kream_name_ko" if kream_name_ko else ""

    sql = text(f"""
        UPDATE samba_collected_product
        SET resell_matches = jsonb_set(
            COALESCE(resell_matches, '{{}}'::jsonb),
            '{{kream}}',
            COALESCE(resell_matches -> 'kream', '{{}}'::jsonb) || {override_obj},
            true
        ){name_set}, updated_at = NOW()
        WHERE source_site = 'SNKRDUNK' AND site_product_id = :sid
    """)
    params: dict[str, Any] = {"sid": snkr_id, "kream_id": kream_id}
    if style_code:
        params["style_code"] = style_code
    if kream_image:
        params["kream_image"] = kream_image
    if kream_name_ko:
        params["kream_name_ko"] = kream_name_ko
    await session.exec(sql.bindparams(**params))  # type: ignore[arg-type]
    await session.commit()
    return {
        "ok": True,
        "kream_name_ko": kream_name_ko,
        "kream_image": kream_image,
        "style_code": style_code,
    }


class SnkrdunkMatchPatchRequest(BaseModel):
    kream_id: str
    kream_name_ko: str = ""
    style_code: str = ""


class SnkrdunkStyleCodePatchRequest(BaseModel):
    style_code: str


class SnkrdunkKreamNamePatchRequest(BaseModel):
    kream_name_ko: str


class SnkrdunkFixedPricePatchRequest(BaseModel):
    option: str  # "PSA 10" / "PSA 9"
    enabled: bool
    price: int = 0


class SnkrdunkKreamNameEnPatchRequest(BaseModel):
    kream_name_en: str


# 인증 없는 퍼블릭 버전 (로컬 크림 입찰/리스톡 스크립트 — samba_tools/kream/*.py — 가 사이클마다 조회)
@snkrdunk_public_router.get("/kream/margin-policy")
async def get_kream_margin_policy_public(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """정책관리 KREAM 탭 설정값 조회 (인증 불필요).

    market_policies(JSON)에 'KREAM' 키가 있는 첫 정책을 사용 — 정책이 여러 개여도
    크림은 계정 단위로 정책 하나만 운용한다는 전제(2026-07-08).
    """
    from backend.domain.samba.policy.model import SambaPolicy

    result = await session.execute(select(SambaPolicy.market_policies))
    for (mp,) in result.all():
        if isinstance(mp, dict) and isinstance(mp.get("KREAM"), dict):
            k = mp["KREAM"]
            return {
                "min_margin_amount": k.get("kreamMinMarginAmount", 9000),
                "competitive_margin_rate": k.get("kreamCompetitiveMarginRate", 13),
                "no_competition_margin_rate": k.get("kreamNoCompetitionMarginRate", 40),
                # 배송비는 엔화(스니덩크 판매자→배대지). 카드 300엔 / 박스 900엔.
                "shipping_fee_card": k.get("kreamShippingFeeCard", 300),
                "shipping_fee_box": k.get("kreamShippingFeeBox", 900),
                # 배대지비용(원, 배대지→한국). 원가에 별도 가산.
                "forwarding_fee": k.get("kreamForwardingFee", 8000),
            }
    raise HTTPException(status_code=404, detail="KREAM 정책 설정 없음")


# 카드 이미지 여백 제거용 bbox 캐시 (url → dict). 검수페이지가 카드만 잘라 붙여 비교하도록 지원.
_IMG_BBOX_CACHE: dict[str, dict[str, Any]] = {}


@snkrdunk_public_router.get("/kream/image-bbox")
async def get_image_bbox_public(url: str) -> dict[str, Any]:
    """이미지에서 '카드 실제 영역'(투명/단색 여백 제외)의 bounding box 계산 (인증 불필요).

    검수페이지가 이 bbox로 카드만 확대·정렬해 두 이미지를 여백 없이 맞닿게 표시한다.
    서버는 CORS 제약이 없어 픽셀 접근 가능(브라우저 canvas는 크로스오리진 차단).
    반환: {x,y,w,h,iw,ih} (원본 픽셀 기준). 실패 시 전체 영역 반환.
    """
    if url in _IMG_BBOX_CACHE:
        return _IMG_BBOX_CACHE[url]

    import io as _io

    import httpx
    from PIL import Image, ImageChops

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            im = Image.open(_io.BytesIO(r.content))
        iw, ih = im.size
        bbox = None
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            # 투명 배경 → 알파 채널로 내용 영역 계산
            alpha = im.convert("RGBA").getchannel("A")
            bbox = alpha.getbbox()
        if bbox is None:
            # 불투명 → 좌상단 코너색을 배경으로 보고 차이나는 영역 계산
            rgb = im.convert("RGB")
            bg = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
            diff = ImageChops.difference(rgb, bg)
            bbox = diff.getbbox()
        if not bbox:
            bbox = (0, 0, iw, ih)
        x0, y0, x1, y1 = bbox
        out = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "iw": iw, "ih": ih}
    except Exception as e:
        logger.warning(f"[image-bbox] 실패({url[:60]}): {e}")
        out = {"x": 0, "y": 0, "w": 0, "h": 0, "iw": 0, "ih": 0, "error": True}
    _IMG_BBOX_CACHE[url] = out
    return out


# 인증 없는 퍼블릭 버전 (로컬 전용 HTML 검수 도구용)
@snkrdunk_public_router.get("/kream/snkrdunk-compare/all")
async def snkrdunk_compare_all_public(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """검수페이지용 전체 SNKRDUNK 상품 목록 (인증 불필요).

    카테고리는 DB 실시간 기준:
    1=PSA10재고O+크림매칭 / 2=재고X+매칭 / 3=재고O+미매칭 / 4=재고X+미매칭
    """
    import json
    import re as _re

    from sqlalchemy import text

    _re_cm = _re.compile(r"([\d.]+)")

    sql = text("""
        SELECT
            site_product_id AS snkr_id,
            name AS snkr_name,
            -- 최근 가격/재고 확인 시각(KST) — restock/갱신이 snkr price·stock 갱신 시 updated_at=NOW()
            to_char(updated_at AT TIME ZONE 'Asia/Seoul', 'MM-DD HH24:MI') AS price_checked_at,
            COALESCE(style_code, '') AS style_code,
            COALESCE(extra_data->>'name_ja', '') AS name_ja,
            COALESCE(extra_data->>'name_en', '') AS name_en,
            COALESCE((images::jsonb)->>0, '') AS snkr_image,
            COALESCE(resell_matches->'kream'->>'product_id', '') AS kream_id,
            COALESCE(resell_matches->'kream'->>'name_ko', '') AS kream_name_ko,
            COALESCE(resell_matches->'kream'->>'name_en', '') AS kream_name_en,
            COALESCE(resell_matches->'kream'->>'image', '') AS kream_image,
            COALESCE(resell_matches->'kream'->>'style_code', '') AS kream_style_code,
            (COALESCE(resell_matches->'kream'->>'verified', '') = 'true') AS verified,
            -- 이상감지 승인(리스톡 허용) — 사용자가 검수페이지에서 확인 후 체크
            (COALESCE(resell_matches->'kream'->>'anomaly_ok', '') = 'true') AS anomaly_ok,
            -- 이상감지 차단됨 — 봇이 저가위험으로 등록/갱신 막은 상품(검수페이지 필터용)
            (COALESCE(resell_matches->'kream'->>'anomaly_flagged', '') = 'true') AS anomaly_flagged,
            -- 이상감지 원인(검수페이지 매입가 아래 표시): "옵션 등록가 X < 시세 Y의 70%"
            COALESCE(resell_matches->'kream'->>'anomaly_reason', '') AS anomaly_reason,
            COALESCE((
                SELECT NULLIF(o->>'stock', '')::int
                FROM jsonb_array_elements(options::jsonb) o
                WHERE REPLACE(o->>'name', ' ', '') = 'PSA10'
                LIMIT 1
            ), 0) AS psa10_stock,
            COALESCE((
                SELECT NULLIF(o->>'price', '')::numeric::int
                FROM jsonb_array_elements(options::jsonb) o
                WHERE REPLACE(o->>'name', ' ', '') = 'PSA10'
                LIMIT 1
            ), 0) AS psa10_price,
            COALESCE((
                SELECT NULLIF(o->>'stock', '')::int
                FROM jsonb_array_elements(options::jsonb) o
                WHERE REPLACE(o->>'name', ' ', '') = 'PSA9'
                LIMIT 1
            ), 0) AS psa9_stock,
            COALESCE((
                SELECT NULLIF(o->>'price', '')::numeric::int
                FROM jsonb_array_elements(options::jsonb) o
                WHERE REPLACE(o->>'name', ' ', '') = 'PSA9'
                LIMIT 1
            ), 0) AS psa9_price,
            -- 옵션별 고정입찰가(원가무관) 설정 — 검수페이지 표시/체크 복원용
            COALESCE((
                SELECT (o->>'fixedEnabled')::boolean
                FROM jsonb_array_elements(options::jsonb) o
                WHERE REPLACE(o->>'name', ' ', '') = 'PSA10'
                LIMIT 1
            ), false) AS psa10_fixed_enabled,
            COALESCE((
                SELECT NULLIF(o->>'fixedPrice', '')::numeric::int
                FROM jsonb_array_elements(options::jsonb) o
                WHERE REPLACE(o->>'name', ' ', '') = 'PSA10'
                LIMIT 1
            ), 0) AS psa10_fixed_price,
            COALESCE((
                SELECT (o->>'fixedEnabled')::boolean
                FROM jsonb_array_elements(options::jsonb) o
                WHERE REPLACE(o->>'name', ' ', '') = 'PSA9'
                LIMIT 1
            ), false) AS psa9_fixed_enabled,
            COALESCE((
                SELECT NULLIF(o->>'fixedPrice', '')::numeric::int
                FROM jsonb_array_elements(options::jsonb) o
                WHERE REPLACE(o->>'name', ' ', '') = 'PSA9'
                LIMIT 1
            ), 0) AS psa9_fixed_price,
            -- 신발(스니커즈)용: 사이즈옵션 전체 재고합 + 최저가(카드 PSA칸 없음 대응)
            COALESCE(extra_data->>'snkr_type', '') AS snkr_type,
            -- 신발만 사이즈옵션 배열 전달(카드는 payload 절약 위해 NULL)
            CASE WHEN extra_data->>'snkr_type' = 'sneaker' THEN options ELSE NULL END AS size_options,
            COALESCE(extra_data->>'currency', '') AS currency,
            -- SUM/MIN 서브쿼리는 신발(스니커즈)만 계산 — 카드 2.5만행 전체에 돌리면
            -- /all 이 29초로 느려져 페이지 로드마다 DB 부하(2026-07-09 성능 회귀 수정).
            CASE WHEN extra_data->>'snkr_type' = 'sneaker' THEN COALESCE((
                SELECT SUM(NULLIF(o->>'stock', '')::int)
                FROM jsonb_array_elements(options::jsonb) o
            ), 0) ELSE 0 END AS total_stock,
            CASE WHEN extra_data->>'snkr_type' = 'sneaker' THEN COALESCE((
                SELECT MIN(NULLIF(o->>'price', '')::numeric)::int
                FROM jsonb_array_elements(options::jsonb) o
                WHERE NULLIF(o->>'price', '')::numeric > 0
            ), 0) ELSE 0 END AS min_opt_price
        FROM samba_collected_product
        WHERE source_site = 'SNKRDUNK'
        ORDER BY site_product_id
    """)
    result = await session.exec(sql)  # type: ignore[arg-type]

    # 검수 등록여부 — 갱신(_kream_ask_adjust)이 매 사이클 저장하는 실시간 크림 입찰 목록.
    # 낡은 입찰엑셀 수동 업로드를 대체 → 등록여부가 즉각 정확해진다.
    # kream_live_asks 테이블이 아직 없으면(첫 갱신 전) 전부 미등록으로 처리.
    registered_set: set[str] = set()
    try:
        reg_res = await session.exec(
            text("SELECT DISTINCT product_id FROM kream_live_asks")  # type: ignore[arg-type]
        )
        registered_set = {row[0] for row in reg_res}
    except Exception:
        registered_set = set()

    # 크림 누적거래수(total_sales) — 검수 등록가능 판별용. 갱신/리스톡이 저장.
    # 카드팩/박스·유희왕·원피스는 거래 1건↑ 있어야 등록가능(포켓몬 개별카드는 무관).
    trade_counts: dict[str, int] = {}
    try:
        tc_res = await session.exec(
            text("SELECT product_id, total_sales FROM kream_trade_counts")  # type: ignore[arg-type]
        )
        trade_counts = {row[0]: int(row[1] or 0) for row in tc_res}
    except Exception:
        trade_counts = {}

    items = []
    for r in result.mappings():
        d = dict(r)
        matched = bool(d["kream_id"])
        is_sneaker = d.get("snkr_type") == "sneaker"
        d["is_sneaker"] = is_sneaker
        # 신발 사이즈옵션 파싱(재고>0만, 사이즈 오름차순) — 프론트 사이즈별 표시용
        if is_sneaker and d.get("size_options"):

            def _cm(name: str) -> float:
                m = _re_cm.search(name or "")
                return float(m.group(1)) if m else 9999.0

            try:
                raw_opts = d["size_options"]
                if isinstance(raw_opts, str):
                    raw_opts = json.loads(raw_opts)
                d["size_options"] = sorted(
                    (
                        {
                            "name": o.get("name", ""),
                            "price": int(o.get("price") or 0),
                            "stock": int(o.get("stock") or 0),
                        }
                        for o in raw_opts
                        if int(o.get("stock") or 0) > 0
                    ),
                    key=lambda x: _cm(x["name"]),
                )
            except Exception:
                d["size_options"] = []
        else:
            d["size_options"] = []
        # PSA10 없어도 PSA9 재고 있으면 재고 있는 것으로 취급.
        # 신발(스니커즈)은 PSA칸이 없으므로 사이즈옵션 전체 재고합으로 판정.
        has_stock = (
            (d["psa10_stock"] or 0) > 0
            or (d["psa9_stock"] or 0) > 0
            or (is_sneaker and (d["total_stock"] or 0) > 0)
        )
        d["has_stock"] = has_stock
        d["model_no"] = d["kream_style_code"]
        d["kream_name"] = d["kream_name_ko"]
        d["cat"] = (1 if has_stock else 2) if matched else (3 if has_stock else 4)
        # DB 실시간 등록여부 (크림에 입찰 존재)
        d["registered"] = bool(d["kream_id"]) and d["kream_id"] in registered_set
        # 크림 누적거래수 (없으면 -1 = 미수집 → 프론트가 KREAM_TRADES fallback)
        d["trade_count"] = trade_counts.get(d["kream_id"], -1) if d["kream_id"] else -1
        items.append(d)
    return {"total": len(items), "items": items}


class SnkrdunkVerifyPatchRequest(BaseModel):
    verified: bool


class SnkrdunkAnomalyOkPatchRequest(BaseModel):
    anomaly_ok: bool


@snkrdunk_public_router.patch("/kream/snkrdunk-compare/{snkr_id}/verify")
async def snkrdunk_update_verify_public(
    snkr_id: str,
    body: SnkrdunkVerifyPatchRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """검수 '일치' 확정 플래그 저장 (자동 입찰 관리 대상 지정, 인증 불필요)."""
    from sqlalchemy import text

    sql = text("""
        UPDATE samba_collected_product
        SET resell_matches = jsonb_set(
            COALESCE(resell_matches, '{}'::jsonb),
            '{kream,verified}',
            CAST(:verified AS jsonb),
            true
        ), updated_at = NOW()
        WHERE source_site = 'SNKRDUNK' AND site_product_id = :sid
    """)
    await session.exec(  # type: ignore[arg-type]
        sql.bindparams(sid=snkr_id, verified="true" if body.verified else "false")
    )
    await session.commit()
    return {"ok": True}


@snkrdunk_public_router.patch("/kream/snkrdunk-compare/{snkr_id}/anomaly-ok")
async def snkrdunk_update_anomaly_ok_public(
    snkr_id: str,
    body: SnkrdunkAnomalyOkPatchRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """이상감지 승인(리스톡 허용) 플래그 저장 (인증 불필요).

    사용자가 검수페이지에서 이상감지 상품 확인 후 체크 → resell_matches.kream.anomaly_ok=true.
    봇(_kream_restock_register / _kream_ask_adjust)이 이 플래그를 읽어 이상감지 가드를
    통과시킴 → 동적가격(시세 추종) 그대로 등록·갱신. (고정가 아님)
    """
    from sqlalchemy import text

    if body.anomaly_ok:
        # 승인 → anomaly_ok=true + anomaly_flagged=false(차단해제) + 원인문구 제거
        sql = text("""
            UPDATE samba_collected_product
            SET resell_matches = jsonb_set(
                jsonb_set(
                    jsonb_set(
                        COALESCE(resell_matches, '{}'::jsonb),
                        '{kream,anomaly_ok}', 'true'::jsonb, true
                    ),
                    '{kream,anomaly_flagged}', 'false'::jsonb, true
                ),
                '{kream,anomaly_reason}', '""'::jsonb, true
            ), updated_at = NOW()
            WHERE source_site = 'SNKRDUNK' AND site_product_id = :sid
        """)
    else:
        # 승인 취소 → anomaly_ok=false (flagged는 봇이 다시 판단)
        sql = text("""
            UPDATE samba_collected_product
            SET resell_matches = jsonb_set(
                COALESCE(resell_matches, '{}'::jsonb),
                '{kream,anomaly_ok}', 'false'::jsonb, true
            ), updated_at = NOW()
            WHERE source_site = 'SNKRDUNK' AND site_product_id = :sid
        """)
    await session.exec(sql.bindparams(sid=snkr_id))  # type: ignore[arg-type]
    await session.commit()
    return {"ok": True}


@snkrdunk_public_router.get("/kream/snkrdunk-compare/{snkr_id}/kream-image")
async def snkrdunk_kream_image_public(
    snkr_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """검수페이지가 보는 상품의 크림 이미지를 1건 실시간 조회+캐시.

    KREAM은 대량 fetch를 차단하므로, 화면에 뜬 상품 1개만 그때그때 가져와
    resell_matches.kream.image 에 저장(자가치유). 이미 있으면 즉시 반환.
    """
    from sqlalchemy import text

    row = (
        await session.exec(
            text("""
                SELECT resell_matches->'kream'->>'product_id' AS pid,
                       resell_matches->'kream'->>'image' AS img
                FROM samba_collected_product
                WHERE source_site='SNKRDUNK' AND site_product_id = :sid
            """).bindparams(sid=snkr_id)  # type: ignore[arg-type]
        )
    ).first()
    if not row or not row.pid:
        return {"image": ""}
    if row.img:
        return {"image": row.img}
    img = ""
    # KREAM 상품페이지 직접fetch(get_product)는 차단 시 엉뚱한 og:image를 반환(오매칭 이미지
    # 사고). 검색 API로 style_code(=snkr id) 검색 → id==product_id **정확일치**한 결과의
    # 이미지만 사용. 일치 결과 없거나 실패면 빈값(틀린 이미지 절대 넣지 않음, 폴백 금지).
    try:
        results = await KreamClient().search(snkr_id, size=10)
        match = next((r for r in results if str(r.get("id")) == str(row.pid)), None)
        imgs = (match.get("images") or []) if match else []
        img = imgs[0] if imgs else ""
    except Exception:
        img = ""
    if img:
        await session.exec(
            text("""
                UPDATE samba_collected_product
                SET resell_matches = jsonb_set(
                    COALESCE(resell_matches, '{}'::jsonb), '{kream,image}',
                    to_jsonb(CAST(:img AS text))
                ), updated_at = NOW()
                WHERE source_site='SNKRDUNK' AND site_product_id = :sid
            """).bindparams(img=img, sid=snkr_id)  # type: ignore[arg-type]
        )
        await session.commit()
    return {"image": img}


@snkrdunk_public_router.delete("/kream/snkrdunk-compare/{snkr_id}/match")
async def snkrdunk_remove_match_public(
    snkr_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """스니덩크 크림 매칭 해제 (인증 불필요)."""
    return await _snkrdunk_remove_match_impl(snkr_id, session)


@snkrdunk_public_router.patch("/kream/snkrdunk-compare/{snkr_id}/match")
async def snkrdunk_update_match_public(
    snkr_id: str,
    body: SnkrdunkMatchPatchRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """스니덩크 크림 매칭 수정 (인증 불필요)."""
    return await _snkrdunk_update_match_impl(
        snkr_id, body.kream_id, session, body.kream_name_ko, body.style_code
    )


@snkrdunk_public_router.patch("/kream/snkrdunk-compare/{snkr_id}/style-code")
async def snkrdunk_update_style_code_public(
    snkr_id: str,
    body: SnkrdunkStyleCodePatchRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """스니덩크 크림 품번(style_code) 직접 수정 (kream API 호출 없음, 인증 불필요)."""
    from sqlalchemy import text

    sql = text("""
        UPDATE samba_collected_product
        SET resell_matches = jsonb_set(
            COALESCE(resell_matches, '{}'::jsonb),
            '{kream,style_code}',
            to_jsonb(CAST(:style_code AS text)),
            true
        ), updated_at = NOW()
        WHERE source_site = 'SNKRDUNK' AND site_product_id = :sid
    """)
    await session.exec(sql.bindparams(sid=snkr_id, style_code=body.style_code))  # type: ignore[arg-type]
    await session.commit()
    return {"ok": True}


@snkrdunk_public_router.patch("/kream/snkrdunk-compare/{snkr_id}/fixed-price")
async def snkrdunk_update_fixed_price_public(
    snkr_id: str,
    body: SnkrdunkFixedPricePatchRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """옵션별 고정입찰가(원가무관) 설정 — 상품관리 OptionPanel과 동일 필드(fixedEnabled/fixedPrice)를
    options 배열의 해당 옵션에 병합. 리프레셔가 옵션을 통째로 갱신할 때도 보존됨(refresher.py 참조).
    """
    from sqlalchemy import text

    sql = text("""
        UPDATE samba_collected_product
        SET options = (
            SELECT jsonb_agg(
                CASE WHEN o->>'name' = :opt_name
                     THEN o || jsonb_build_object('fixedEnabled', :enabled, 'fixedPrice', :price)
                     ELSE o END)
            FROM jsonb_array_elements(options::jsonb) o
        ), updated_at = NOW()
        WHERE source_site = 'SNKRDUNK' AND site_product_id = :sid
    """)
    await session.exec(
        sql.bindparams(
            sid=snkr_id, opt_name=body.option, enabled=body.enabled, price=body.price
        )  # type: ignore[arg-type]
    )
    await session.commit()
    return {"ok": True}


@snkrdunk_public_router.patch("/kream/snkrdunk-compare/{snkr_id}/kream-name")
async def snkrdunk_update_kream_name_public(
    snkr_id: str,
    body: SnkrdunkKreamNamePatchRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """스니덩크 크림 한글명 직접 수정 (인증 불필요)."""
    from sqlalchemy import text

    sql = text("""
        UPDATE samba_collected_product
        SET name = CAST(:kream_name_ko AS text), updated_at = NOW()
        WHERE source_site = 'SNKRDUNK' AND site_product_id = :sid
    """)
    await session.exec(sql.bindparams(sid=snkr_id, kream_name_ko=body.kream_name_ko))  # type: ignore[arg-type]
    await session.commit()
    return {"ok": True}


@snkrdunk_public_router.patch("/kream/snkrdunk-compare/{snkr_id}/kream-name-en")
async def snkrdunk_update_kream_name_en_public(
    snkr_id: str,
    body: SnkrdunkKreamNameEnPatchRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """스니덩크 크림 영문명(resell_matches.kream.name_en) 직접 수정 (인증 불필요)."""
    from sqlalchemy import text

    sql = text("""
        UPDATE samba_collected_product
        SET resell_matches = jsonb_set(
            COALESCE(resell_matches, '{}'::jsonb),
            '{kream,name_en}',
            to_jsonb(CAST(:name_en AS text)),
            true
        ), updated_at = NOW()
        WHERE source_site = 'SNKRDUNK' AND site_product_id = :sid
    """)
    await session.exec(sql.bindparams(sid=snkr_id, name_en=body.kream_name_en))  # type: ignore[arg-type]
    await session.commit()
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
