"""롯데홈쇼핑 관련 엔드포인트."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.proxy.lottehome import LotteApiError, LotteHomeClient
from backend.domain.samba.tenant.middleware import require_admin
from backend.utils.logger import logger

from ._helpers import _get_lotte_client, _set_setting

router = APIRouter(tags=["samba-proxy"])


class LotteAuthRequest(BaseModel):
    userId: str
    password: str
    agncNo: Optional[str] = ""
    env: Optional[str] = "test"


@router.post("/lottehome/auth")
async def lottehome_auth(
    body: LotteAuthRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
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
        logger.warning(f"[롯데홈] 인증 실패 (LotteApiError): {exc}")
        return {"success": False, "message": str(exc), "code": exc.code}
    except Exception as exc:
        logger.error(f"[롯데홈] 인증 예외: {exc}")
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
        logger.warning(f"[롯데홈] 브랜드 조회 실패: {exc}")
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
        logger.warning(f"[롯데홈] 카테고리 조회 실패: {exc}")
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
        logger.warning(f"[롯데홈] MD상품군 조회 실패: {exc}")
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
        logger.warning(f"[롯데홈] 배송비정책 조회 실패: {exc}")
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/lottehome/delivery-places")
async def lottehome_delivery_places(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 배송지 조회."""
    client = await _get_lotte_client(session)
    try:
        result = await client.search_return_places()
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        logger.warning(f"[롯데홈] 배송지 조회 실패: {exc}")
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
        logger.error(f"[롯데홈] 신규상품등록 실패: {exc}")
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
        logger.error(f"[롯데홈] 신규상품수정 실패 (req={goods_req_no}): {exc}")
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
        logger.error(f"[롯데홈] 전시상품수정 실패 (goods_no={goods_no}): {exc}")
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
        logger.warning(f"[롯데홈] 판매상태 변경 실패 (goods_no={goods_no}): {exc}")
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
        logger.error(f"[롯데홈] 재고수정 실패 (goods_no={body.goods_no}): {exc}")
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
        logger.warning(f"[롯데홈] 재고 조회 실패 (goods_no={goods_no}): {exc}")
        return {"success": False, "message": str(exc), "code": exc.code}
