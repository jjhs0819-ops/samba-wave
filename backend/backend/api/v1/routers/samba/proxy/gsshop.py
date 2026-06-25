"""GS샵 관련 엔드포인트."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.account.resolver import resolve_market_creds
from backend.domain.samba.proxy.gsshop import GsShopApiError, GsShopClient
from backend.domain.samba.tenant.middleware import get_optional_tenant_id, require_admin

from ._helpers import _get_gs_client, _set_setting

router = APIRouter(tags=["samba-proxy"])


def _gs_client_from_creds(creds: dict) -> GsShopClient:
    return GsShopClient(
        sup_cd=creds.get("supCd", ""),
        aes_key=creds.get("aesKey", ""),
        sub_sup_cd=creds.get("subSupCd", ""),
        env=creds.get("env", "dev"),
    )


class GsShopCredsRequest(BaseModel):
    supCd: str
    aesKey: str
    subSupCd: Optional[str] = ""
    env: Optional[str] = "dev"


@router.post("/gsshop/auth/save")
async def gsshop_save_credentials(
    body: GsShopCredsRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
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
    account_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> dict[str, Any]:
    """GS샵 브랜드 조회 (계정별 자격증명 사용)."""
    creds = await resolve_market_creds(
        session,
        tenant_id,
        market_type="gsshop",
        store_key="store_gsshop",
        account_id=account_id,
        allow_default_fallback=True,
    )
    if not creds.get("supCd"):
        return {"success": False, "message": "GS샵 계정 설정 없음", "data": None}
    client = _gs_client_from_creds(creds)
    # getPrdBrandList는 영문명(brandEngNm) 기준 검색이라 한글 입력은 0건.
    # 한글 브랜드명은 brand_en 매핑으로 영문 변환 후 검색 (예: 아디다스→ADIDAS).
    _search_nm = brandNm
    if brandNm:
        from backend.domain.samba.policy.brand_en import brand_en

        _eng = brand_en(brandNm)
        if _eng:
            _search_nm = _eng
    try:
        result = await client.get_brands(
            brand_nm=_search_nm, from_dtm=fromDtm, to_dtm=toDtm
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
    account_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> dict[str, Any]:
    """GS샵 출고지/반송지 조회 (계정별 자격증명 — md-list/brands 와 동일 계정 조회).

    account_id 미지정 시 활성 계정 폴백. _get_gs_client(활성계정) 로만 조회하면
    정책의 GS 계정과 다른 계정(출고지 미등록)을 봐서 빈 목록 → 0001 폴백되던 문제 해소.
    """
    creds = await resolve_market_creds(
        session,
        tenant_id,
        market_type="gsshop",
        store_key="store_gsshop",
        account_id=account_id,
        allow_default_fallback=True,
    )
    if not creds.get("supCd"):
        return {"success": False, "message": "GS샵 계정 설정 없음", "data": None}
    client = _gs_client_from_creds(creds)
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
    account_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> dict[str, Any]:
    """GS샵 협력사 MDID 조회 (계정별 자격증명 사용)."""
    creds = await resolve_market_creds(
        session,
        tenant_id,
        market_type="gsshop",
        store_key="store_gsshop",
        account_id=account_id,
        allow_default_fallback=True,
    )
    if not creds.get("supCd"):
        return {"success": False, "message": "GS샵 계정 설정 없음", "data": None}
    client = _gs_client_from_creds(creds)
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
    if (
        not body.saleproAgreeDocNo
        or not body.pmoReqNo
        or not body.prdCd
        or not body.aprvStCd
    ):
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
