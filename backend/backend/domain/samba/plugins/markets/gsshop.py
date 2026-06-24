"""GS샵 마켓 플러그인.

기존 dispatcher._handle_gsshop + _transform_for_gsshop 로직을 플러그인 구조로 추출.
인증 로드는 base._load_auth 가 처리하므로 execute 에서는 creds dict 사용.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils import add_lazy_loading
from backend.utils.logger import logger


async def _get_setting(session, key: str) -> Any:
    """samba_settings 테이블에서 설정값 조회 후 즉시 커밋 — idle in transaction 방지."""
    from backend.domain.samba.forbidden.model import SambaSettings
    from sqlmodel import select

    stmt = select(SambaSettings).where(SambaSettings.key == key)
    result = await session.execute(stmt)
    row = result.scalars().first()
    val = row.value if row else None
    try:
        await session.commit()
    except Exception:
        pass
    return val


def _build_attr_prd_list(
    options: list[dict[str, Any]],
    sale_str_dtm: int,
    sale_end_dtm: int = 29991231235959,
    brand: str = "",
) -> list[dict[str, Any]]:
    """product options → GS샵 V3 attrPrdList 변환.

    options 구조: {"no": int, "name": str, "price": int, "stock": int, "isSoldOut": bool}
    """
    result = []
    for opt in options:
        name = str(opt.get("name") or "").strip()
        if not name:
            continue
        stock = int(opt.get("stock") or 0)
        is_sold_out = opt.get("isSoldOut", False) or stock <= 0
        result.append(
            {
                "attrPrdListSupAttrPrdCd": str(opt.get("no") or name)[:50],
                "attrPrdListSaleStrDtm": sale_str_dtm,
                "attrPrdListSaleEndDtm": sale_end_dtm,
                "attrPrdListAttrVal1": name,
                "attrPrdListAttrVal2": "None",
                "attrPrdListAttrVal3": "None",
                "attrPrdListAttrVal4": "None",
                "attrPrdListOrgpNm": "국내",
                "attrPrdListMnfcCoNm": brand or "",
                "attrPrdListSafeStockQty": max(0, stock),
                "attrPrdListTempoutYn": "Y" if is_sold_out else "N",
                "attrPrdListOrdPsblQty": 0 if is_sold_out else max(1, stock),
            }
        )
    return result


def _transform_for_gsshop(
    product: dict[str, Any],
    category_id: str,
    sub_sup_cd: str = "",
    gs_margin_rate: int = 0,
    gs_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """수집 상품 → GS샵 V3 ProductV3 형식 변환.

    gs_settings 는 policy.market_policies["GS샵"]["gsSettings"] 에서 전달.
    필수 코드값(brandCd, prdClsCd, dlvsCoCd, operMdId 등)은 여기서 읽는다.
    govPublsItmList: 의류 기준 코드 1001~1009 사용 (getPrdClsDtlInfo API 확인값).
    """
    from datetime import datetime, timezone, timedelta

    gs = gs_settings or {}
    images = product.get("images") or []
    sale_price = int(product.get("sale_price") or 0)
    brand = str(product.get("brand") or "")
    name = str(product.get("name") or "")

    # 판매 기간 (KST 현재 ~ 9999-12-31)
    kst = timezone(timedelta(hours=9))
    now_dtm = int(datetime.now(kst).strftime("%Y%m%d%H%M%S"))
    end_dtm = 29991231235959

    # 공급가 계산 — 마진율 있으면 역산 후 10원 단위 버림 (GS API 원단위 거부)
    if gs_margin_rate:
        sup_prc = int(sale_price * (100 - gs_margin_rate) / 100 / 10) * 10
    else:
        sup_prc = sale_price

    # 옵션 → V3 attrPrdList
    options = product.get("options") or []
    attr_prd_list = _build_attr_prd_list(options, now_dtm, end_dtm, brand)

    # 첫 옵션 타입명 추출 (상품 유형 라벨)
    first_opt_name = ""
    if options:
        first_nm = str(options[0].get("name") or "")
        # "사이즈: M" 형태면 "사이즈"만 추출
        first_opt_name = first_nm.split(":")[0].strip() if ":" in first_nm else "사이즈"

    # 전시매장 — sectid 정수형
    # category_id 형식: "B43071905|1662750" (prdClsCd|sectId) 또는 숫자(sectId만)
    prd_sect_list: list[dict[str, Any]] = []
    category_prd_cls_cd: str = ""
    if category_id:
        if "|" in str(category_id):
            parts = str(category_id).split("|", 1)
            category_prd_cls_cd = parts[0].strip()
            sect_id_str = parts[1].strip()
        else:
            sect_id_str = str(category_id)
        try:
            sect_id = int(sect_id_str)
        except (ValueError, TypeError):
            sect_id = 0
        if sect_id:
            prd_sect_list.append(
                {
                    "prdSectListSectid": sect_id,
                    "prdSectListSectGbn": "S",
                    "prdSectListSectStdYn": "Y",
                }
            )

    # 협력사 상품코드 — style_code > site_product_id > id 순
    sup_prd_cd = str(
        product.get("style_code")
        or product.get("site_product_id")
        or product.get("id")
        or ""
    )

    detail_html = product.get("detail_html") or f"<p>{name}</p>"

    # 이미지 URL (리스트)
    img_urls: list[str] = []
    for img in images:
        url = img if isinstance(img, str) else (img.get("url") or img.get("src") or "")
        if url:
            img_urls.append(url)

    img_info: dict[str, Any] = {}
    if img_urls:
        img_info["prdCntntListCntntUrlNm"] = img_urls

    # 교환/반품비
    rtp_amt = int(gs.get("rtpAmt") or 5000)
    exch_amt = int(gs.get("exchAmt") or 5000)

    # 출고일 (당일=0이면 당일출고마감시간 입력 가능)
    std_rels_ddcnt = int(gs.get("stdRelsDdcnt") or 1)
    base_add_info: dict[str, Any] = {
        "prdNm": name,
        "brandCd": gs.get("brandCd") or "",
        "prdClsCd": category_prd_cls_cd or gs.get("prdClsCd") or "",
        # 3100=직송(택배), 3200=직송(설치)
        "dlvPickMthodCd": int(gs.get("dlvPickMthodCd") or 3100),
        "dlvsCoCd": str(gs.get("dlvsCoCd") or "DH"),
        "saleStrDtm": now_dtm,
        "saleEndDtm": end_dtm,
        "mnfcCoNm": gs.get("mnfcCoNm") or brand,
        "operMdId": int(gs.get("operMdId") or 0),
        "orgpNm": gs.get("orgpNm") or "국내",
        # 02=일반(택배)
        "ordPrdTypCd": str(gs.get("ordPrdTypCd") or "02"),
        # 02=과세
        "taxTypCd": str(gs.get("taxTypCd") or "02"),
        # S=단일옵션
        "prdTypCd": str(gs.get("prdTypCd") or "S"),
        "chrDlvYn": "N",
        "chrDlvcAmt": 0,
        "shipLimitAmt": 0,
        "exchRtpChrYn": "Y",
        "rtpAmt": rtp_amt,
        "exchAmt": exch_amt,
        "chrDlvAddYn": "N",
        "ilndDlvPsblYn": "N",
        "jejuDlvPsblYn": "N",
        "bundlDlvCd": str(gs.get("bundlDlvCd") or "A01"),
        "clerncUniqSignNeedYn": "N",
        "openAftRtpNoadmtYn": "Y",
        "prdRelspAddrCd": str(gs.get("prdRelspAddrCd") or "0001"),
        "prdRetpAddrCd": str(gs.get("prdRetpAddrCd") or "0001"),
        "ordMnfcYn": "N",
        "attrTypExposCd": "L",
        "adultCertYn": "N",
        "frmlesPrdTypCd": "N",
        "attrTypNm1": first_opt_name or "사이즈",
        "paraImPrdYn": "N",
        "prdBaseCmposCntnt": name,
        "orgprdPkgCnt": 1,
        "prdUnitValCd40": "A01",
        "prdUnitValCd20": "B01",
        "rfnTypCd": 20,
        "supTmDlvCntnt": str(gs.get("supTmDlvCntnt") or "출고 2~3일"),
        "stdRelsDdcnt": std_rels_ddcnt,
        "prdStoreMthodCd": 10,
    }
    # 당일출고(0)인 경우에만 마감시간 입력
    if std_rels_ddcnt == 0 and gs.get("thedayRelsOrdDedlnTime") is not None:
        base_add_info["thedayRelsOrdDedlnTime"] = int(gs["thedayRelsOrdDedlnTime"])

    payload: dict[str, Any] = {
        "supPrdCd": sup_prd_cd,
        "subSupCd": sub_sup_cd if sub_sup_cd else None,
    }
    payload.update(
        {
            "prdBaseAddInfo": base_add_info,
            "prdPrcInfo": {
                "prdPrcValidStrDtm": now_dtm,
                "prdPrcValidEndDtm": end_dtm,
                "prdPrcSalePrc": sale_price,
                "prdPrcSupGivRtamt": sup_prc,
                "prdPrcSupGivRtamtCd": "01",
            },
            "prdNmChgInfo": {
                "prdNmChgExposPrdNm": name,
                "prdNmChgValidStrDtm": now_dtm,
                "prdNmChgValidEndDtm": end_dtm,
            },
            "prdImgInfo": img_info,
            "prdDescdHtmlInfo": {
                "prdDescdHtmlDescdExplnCntnt": add_lazy_loading(detail_html),
            },
            "attrPrdList": attr_prd_list,
            "prdSectList": prd_sect_list,
            # 안전인증 — 의류는 safeCertGbnCd=0 (해당없음)
            "prdSafeCertInfo": gs.get("prdSafeCertInfo")
            or {"safeCertGbnCd": 0, "safeCertOrgCd": 0},
            # 정보고시 — 의류 코드 1001~1009 (getPrdClsDtlInfo API 확인값)
            # gs_settings에 없으면 "상품 페이지 참조" 기본값으로 채움
            "prdGovPublsItmList": gs.get("prdGovPublsItmList")
            or [
                {"govPublsItmCd": "1001", "govPublsItmCntnt": "상품 페이지 참조"},
                {"govPublsItmCd": "1002", "govPublsItmCntnt": "상품 페이지 참조"},
                {"govPublsItmCd": "1003", "govPublsItmCntnt": "상품 페이지 참조"},
                {"govPublsItmCd": "1004", "govPublsItmCntnt": "상품 페이지 참조"},
                {"govPublsItmCd": "1005", "govPublsItmCntnt": "해외"},
                {"govPublsItmCd": "1006", "govPublsItmCntnt": "상품 페이지 참조"},
                {"govPublsItmCd": "1007", "govPublsItmCntnt": "상품 페이지 참조"},
                {"govPublsItmCd": "1008", "govPublsItmCntnt": "상품 페이지 참조"},
                {"govPublsItmCd": "1009", "govPublsItmCntnt": "상품 페이지 참조"},
            ],
        }
    )
    return payload


class GsShopPlugin(MarketPlugin):
    market_type = "gsshop"
    policy_key = "GS샵"
    required_fields = ["name", "sale_price"]

    def _validate_category(self, category_id: str) -> str:
        """GS샵은 B코드(prdClsCd) 또는 숫자(prdSectListSectid) 모두 허용."""
        return category_id or ""

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """상품 데이터 → GS샵 API 포맷 변환."""
        gs_margin_rate = kwargs.get("gs_margin_rate", 0)
        sub_sup_cd = kwargs.get("sub_sup_cd", "")
        gs_settings = kwargs.get("gs_settings") or {}
        return _transform_for_gsshop(
            product, category_id, sub_sup_cd, gs_margin_rate, gs_settings
        )

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """GS샵 상품 등록 — 전체 로직."""
        from backend.domain.samba.proxy.gsshop import GsShopClient

        # creds가 비었으면 settings에서 조회.
        # (2026-05-25) store_gsshop 직접 호출 → resolver 위임 + account.tenant_id 자동 추출.
        auth_creds = dict(creds) if creds else {}
        if not auth_creds:
            auth_creds = await _get_setting(session, "gsshop_credentials") or {}
        if not auth_creds or not isinstance(auth_creds, dict):
            from backend.domain.samba.account.resolver import resolve_market_creds

            _tid = getattr(account, "tenant_id", None) if account else None
            auth_creds = (
                await resolve_market_creds(
                    session, _tid, market_type="gsshop", store_key="store_gsshop"
                )
                or {}
            )
        # account의 additional_fields에서 fallback
        if (not auth_creds or not isinstance(auth_creds, dict)) and account:
            extra = getattr(account, "additional_fields", None) or {}
            if (
                extra.get("supCd")
                or extra.get("aesKey")
                or extra.get("apiKeyProd")
                or extra.get("apiKeyDev")
            ):
                auth_creds = extra
        if not auth_creds or not isinstance(auth_creds, dict):
            return {"success": False, "message": "GS샵 설정이 없습니다."}

        sup_cd = (
            auth_creds.get("supCd", "")
            or auth_creds.get("storeId", "")
            or auth_creds.get("vendorId", "")
        )
        # account.seller_id fallback (계정에 supCd가 seller_id로 저장된 경우)
        if not sup_cd and account:
            sup_cd = getattr(account, "seller_id", "") or ""
        aes_key = (
            auth_creds.get("aesKey", "")
            or auth_creds.get("apiKeyProd", "")
            or auth_creds.get("apiKeyDev", "")
        )
        sub_sup_cd = auth_creds.get("subSupCd") or sup_cd
        env = "prod" if auth_creds.get("apiKeyProd") else auth_creds.get("env", "dev")

        # 정책에서 GS샵 마켓마진율 + 기타 등록 설정 조회
        gs_margin_rate = 0
        gs_settings: dict[str, Any] = {}
        policy_id = product.get("applied_policy_id")
        if policy_id:
            from backend.domain.samba.policy.repository import SambaPolicyRepository

            policy_repo = SambaPolicyRepository(session)
            policy = await policy_repo.get_async(policy_id)
            if policy and policy.market_policies:
                gs_policy = policy.market_policies.get("GS샵", {})
                gs_margin_rate = gs_policy.get("gsMarginRate", 0)
                # brandCd, prdClsCd, dlvsCoCd, prdRelspAddrCd 등 등록에 필요한 코드값
                gs_settings = gs_policy.get("gsSettings") or {}

        # 계정 설정 반품/교환비 fallback (정책 gsSettings에 없을 때)
        if not gs_settings.get("rtpAmt") and auth_creds.get("returnFee"):
            gs_settings = {**gs_settings, "rtpAmt": int(auth_creds["returnFee"])}
        if not gs_settings.get("exchAmt") and auth_creds.get("exchangeFee"):
            gs_settings = {**gs_settings, "exchAmt": int(auth_creds["exchangeFee"])}

        client = GsShopClient(sup_cd, aes_key, sub_sup_cd, env)

        # operMdId 미설정 시 MD 목록 API에서 자동 조회
        if not gs_settings.get("operMdId"):
            try:
                md_result = await client.get_md_list()
                md_list = (md_result.get("data", {}) or {}).get("resultList") or []
                if md_list:
                    gs_settings = {
                        **gs_settings,
                        "operMdId": int(md_list[0].get("mdId") or 0),
                    }
            except Exception:
                pass

        # 기존 상품번호(prdCd) 있으면 수정 모드 — 가격+옵션(재고) 업데이트
        if existing_no:
            return await self._update_gsshop(
                client, product, existing_no, gs_margin_rate, gs_settings, sub_sup_cd
            )

        goods_data = _transform_for_gsshop(
            product, category_id, sub_sup_cd, gs_margin_rate, gs_settings
        )
        result = await client.register_goods(goods_data)

        # GS샵 API 응답 검증 — HTTP 200이지만 본문에 fail 포함 가능
        # 응답 구조: result["data"] = raw API JSON, raw["data"] = {"prdCd": "..."}
        raw = result.get("data", {})
        if isinstance(raw, dict):
            if raw.get("result") == "fail" or (
                raw.get("result") and raw.get("result") != "success"
            ):
                msg = raw.get("message", "") or raw.get("code", "") or "등록 실패"
                return {
                    "success": False,
                    "message": f"GS샵 등록 실패: {msg}",
                    "data": raw,
                }

        # prdCd 추출 — {"data": {"data": {"prdCd": "..."}}}
        inner = raw.get("data", {}) if isinstance(raw, dict) else {}
        prd_cd = inner.get("prdCd") if isinstance(inner, dict) else None
        # supPrdCd(=업체상품코드=style_code) 를 product_id로 저장
        # GS API 수정/삭제 endpoint URL이 supPrdCd 기준 (/api/v3/products/{supPrdCd}/price)
        sup_prd_cd_registered = goods_data.get("supPrdCd") or str(prd_cd or "")

        return {
            "success": True,
            "message": "GS샵 등록 성공",
            "product_id": sup_prd_cd_registered,
            "data": result,
        }

    async def _update_gsshop(
        self,
        client: Any,
        product: dict[str, Any],
        prd_cd: str,
        gs_margin_rate: int,
        gs_settings: dict[str, Any],
        sub_sup_cd: str,
    ) -> dict[str, Any]:
        """GS샵 기존 상품 수정 — 가격 + 옵션(재고) 업데이트."""
        from datetime import datetime, timezone, timedelta

        kst = timezone(timedelta(hours=9))
        now_dtm = int(datetime.now(kst).strftime("%Y%m%d%H%M%S"))
        end_dtm = 29991231235959

        sale_price = int(product.get("sale_price") or 0)
        if gs_margin_rate:
            sup_prc = int(sale_price * (100 - gs_margin_rate) / 100 / 10) * 10
        else:
            sup_prc = sale_price

        brand = str(product.get("brand") or "")
        options = product.get("options") or []
        attr_prd_list = _build_attr_prd_list(options, now_dtm, end_dtm, brand)

        errors = []
        _price_md_pending = False

        # 가격 수정
        price_result = await client.update_goods_price(
            prd_cd,
            {
                "prdPrcValidStrDtm": now_dtm,
                "prdPrcValidEndDtm": end_dtm,
                "prdPrcSalePrc": sale_price,
                "prdPrcSupGivRtamt": sup_prc,
                "prdPrcSupGivRtamtCd": "01",
            },
        )
        price_raw = price_result.get("data", {})
        if isinstance(price_raw, dict):
            _pr = price_raw.get("result", "")
            _pm = price_raw.get("message", "")
            if _pr == "fail":
                errors.append(f"가격: {_pm or '실패'}")
            elif _pr == "success":
                # "요청" 포함 = MD승인 대기 (즉시반영 아님)
                # 즉시반영: "P : 처리하였습니다."
                # MD대기: "P : 가격변경 요청되었습니다."
                if "요청" in _pm or "대기" in _pm:
                    _price_md_pending = True
                    logger.info(
                        f"[GS샵] 가격 MD승인 대기: {prd_cd} → {sale_price}원 (승인 후 반영)"
                    )

        # 옵션/재고 수정 (옵션 있을 때만)
        if attr_prd_list:
            attr_result = await client.update_attributes(
                prd_cd,
                attr_prd_list,
                prd_typ_cd=str(gs_settings.get("prdTypCd") or "S"),
                sub_sup_cd=sub_sup_cd,
            )
            attr_raw = attr_result.get("data", {})
            if isinstance(attr_raw, dict) and attr_raw.get("result") == "fail":
                errors.append(f"재고: {attr_raw.get('message', '실패')}")

        if errors:
            return {
                "success": False,
                "message": f"GS샵 수정 실패: {'; '.join(errors)}",
                "product_id": prd_cd,
            }

        if _price_md_pending:
            return {
                "success": True,
                # 롯데홈쇼핑과 동일한 md_pending 규약 — 오토튠 재전송 폭주 방지
                "approval": "md_pending",
                "message": "GS샵 가격 MD승인 대기 (승인 후 반영)",
                "product_id": prd_cd,
            }

        return {
            "success": True,
            "message": "GS샵 수정 성공",
            "product_id": prd_cd,
            "data": price_result,
        }
