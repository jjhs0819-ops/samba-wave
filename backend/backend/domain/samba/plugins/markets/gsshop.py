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


_GS_CATEGORY_MAP_CACHE: dict[str, str] | None = None


def _load_gs_category_map() -> dict[str, str]:
    """소싱카테고리 → "prdClsCd|sectId" 기본 매핑(레포 커밋 JSON). 모듈 레벨 캐시."""
    global _GS_CATEGORY_MAP_CACHE
    if _GS_CATEGORY_MAP_CACHE is None:
        import json
        import os

        path = os.path.join(os.path.dirname(__file__), "gsshop_category_map.json")
        try:
            with open(path, encoding="utf-8") as f:
                _GS_CATEGORY_MAP_CACHE = json.load(f)
        except Exception:
            _GS_CATEGORY_MAP_CACHE = {}
    return _GS_CATEGORY_MAP_CACHE


async def _resolve_gs_category_id(
    session: Any, product: dict[str, Any], category_id: str
) -> str:
    """category_id가 비었으면 상품의 소싱 카테고리로 자동매핑(prdClsCd|sectId).
    레포 커밋 JSON(gsshop_category_map.json) + DB 설정(gsshop_category_map) 병합.
    베이스 handle()의 카테고리 검증 전에 호출되어야 자동매칭이 동작한다.
    """
    if category_id:
        return category_id
    src_cat = str(product.get("category") or "").strip()
    if not src_cat:
        return category_id
    cat_map = dict(_load_gs_category_map())
    db_map = await _get_setting(session, "gsshop_category_map")
    if isinstance(db_map, dict):
        cat_map.update(db_map)
    matched = cat_map.get(src_cat)
    if matched:
        logger.info(f"[GS샵] 카테고리 자동매칭: '{src_cat}' → {matched}")
        return str(matched)
    return category_id


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


_ORIGIN_KO = {
    "china": "중국",
    "vietnam": "베트남",
    "korea": "대한민국",
    "indonesia": "인도네시아",
    "cambodia": "캄보디아",
    "bangladesh": "방글라데시",
    "india": "인도",
    "thailand": "태국",
    "myanmar": "미얀마",
    "philippines": "필리핀",
    "taiwan": "대만",
    "japan": "일본",
}


def _truncate_prdnm(name: str, max_bytes: int = 30) -> str:
    """GS 송장명(prdNm)=VARCHAR2(30)=30바이트. 특수문자 제거 후 한글 글자경계 안 깨지게 절단.
    노출상품명(prdNmChgExposPrdNm, 240자)은 풀로 유지하고 송장명만 줄인다.
    GS 송장명은 콜론/슬래시 등 특수문자 불가 → 공백으로 치환.
    """
    import re

    s = re.sub(r"[:/\\|<>\"'~^*]", " ", name)
    s = re.sub(r"\s+", " ", s).strip()
    out = ""
    for ch in s:
        try:
            nb = len((out + ch).encode("euc-kr"))
        except UnicodeEncodeError:
            nb = len((out + ch).encode("utf-8"))
        if nb > max_bytes:
            break
        out += ch
    return out.strip() or s[:15]


def _build_gov_publs(
    product: dict[str, Any], brand: str, prd_cls_cd: str
) -> list[dict[str, str]]:
    """정보고시 — 분류(prdClsCd)별 그룹. B25=신발(1101~1109), 그외=의류(1001~1009).
    수집데이터(소재·색상·제조자·제조국 등) 우선, 없으면 '상품 페이지 참조' (메모리 원칙).
    """

    def g(v: Any, default: str = "상품 페이지 참조") -> str:
        s = str(v or "").strip()
        return s if s else default

    origin = str(product.get("origin") or "").strip()
    origin_ko = _ORIGIN_KO.get(origin.lower(), origin) if origin else "상품 페이지 참조"
    material = g(product.get("material"))
    color = g(product.get("color"))
    maker = g(product.get("manufacturer") or brand)
    care = g(product.get("care_instructions"))
    as_phone = g(product.get("as_phone"))
    quality = g(
        product.get("quality_guarantee"), "관련 법령 및 소비자분쟁해결기준에 따름"
    )

    if str(prd_cls_cd).startswith("B25"):  # 신발 (그룹11: 1101~1109)
        return [
            {"govPublsItmCd": "1101", "govPublsItmCntnt": material},
            {"govPublsItmCd": "1102", "govPublsItmCntnt": color},
            {
                "govPublsItmCd": "1103",
                "govPublsItmCntnt": g(product.get("size_notice")),
            },
            {
                "govPublsItmCd": "1104",
                "govPublsItmCntnt": g(product.get("heel_height"), "해당없음"),
            },
            {"govPublsItmCd": "1105", "govPublsItmCntnt": maker},
            {"govPublsItmCd": "1106", "govPublsItmCntnt": origin_ko},
            {"govPublsItmCd": "1107", "govPublsItmCntnt": quality},
            {"govPublsItmCd": "1108", "govPublsItmCntnt": as_phone},
            {"govPublsItmCd": "1109", "govPublsItmCntnt": care},
        ]
    # 의류 (그룹10: 1001~1009)
    return [
        {"govPublsItmCd": "1001", "govPublsItmCntnt": material},
        {"govPublsItmCd": "1002", "govPublsItmCntnt": color},
        {"govPublsItmCd": "1003", "govPublsItmCntnt": g(product.get("size_notice"))},
        {"govPublsItmCd": "1004", "govPublsItmCntnt": maker},
        {"govPublsItmCd": "1005", "govPublsItmCntnt": origin_ko},
        {"govPublsItmCd": "1006", "govPublsItmCntnt": care},
        {
            "govPublsItmCd": "1007",
            "govPublsItmCntnt": g(product.get("manufacture_date")),
        },
        {"govPublsItmCd": "1008", "govPublsItmCntnt": quality},
        {"govPublsItmCd": "1009", "govPublsItmCntnt": as_phone},
    ]


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

    # 브랜드코드 — 정책 gsSettings.brands[](멀티선택)에서 상품 브랜드와 매칭.
    # 정책 UI는 brands 배열로 저장하는데 legacy 단일 brandCd만 읽으면 비어서 GS 등록 실패함.
    def _resolve_brand_cd() -> str:
        single = str(gs.get("brandCd") or "")
        brands = gs.get("brands") or []
        if not brands:
            return single

        def _bn(b: dict[str, Any]) -> str:
            return str(b.get("brandNm") or "").strip().lower().replace(" ", "")

        pb = brand.strip().lower().replace(" ", "")
        pn = name.lower().replace(" ", "")
        # 1) 정확 일치 최우선 (전체 스캔) — "나이키" 상품이 "나이키 키즈"에 잘못 매칭되는 것 방지
        if pb:
            for b in brands:
                if _bn(b) and _bn(b) == pb:
                    return str(b.get("brandCd") or "")
        # 2) 정책 브랜드명이 상품 브랜드명에 포함 (예: 상품 "나이키골프" ⊃ 정책 "나이키").
        #    구체적(긴) 브랜드명 우선해 "나이키 키즈"가 "나이키"보다 먼저 매칭되게.
        #    주의: 반대방향(상품브랜드 ⊂ 정책브랜드)은 "나이키"→"나이키 키즈" 오매칭이라 제외.
        if pb:
            for b in sorted(brands, key=lambda x: -len(_bn(x))):
                if _bn(b) and _bn(b) in pb:
                    return str(b.get("brandCd") or "")
        # 3) 상품명에 정책 브랜드명 포함 (긴 것 우선)
        for b in sorted(brands, key=lambda x: -len(_bn(x))):
            if _bn(b) and _bn(b) in pn:
                return str(b.get("brandCd") or "")
        # 4) 폴백: legacy 단일 brandCd → 브랜드가 1개뿐일 때만 그 브랜드.
        #    매칭 실패 + 다중 브랜드면 임의 선택(오등록)하지 말고 빈값 → GS가 brandCd 필수로 막게 둠.
        if single:
            return single
        if len(brands) == 1:
            return str((brands[0] or {}).get("brandCd") or "")
        return ""

    brand_cd = _resolve_brand_cd()

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
        "prdNm": _truncate_prdnm(name),
        "brandCd": brand_cd,
        "prdClsCd": category_prd_cls_cd or gs.get("prdClsCd") or "",
        # 3100=직송(설치), 3200=직송(택배) — 택배사(dlvsCoCd)는 직송(택배)일 때만 적용됨
        "dlvPickMthodCd": int(gs.get("dlvPickMthodCd") or 3200),
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
        # 도서산간/제주 배송가능(Y) + 추가배송비·반품비·교환비 5000원(직송택배라 추가유료배송 가능)
        "ilndDlvPsblYn": "Y",
        "ilndChrDlvYn": "Y",
        "ilndChrDlvcAmt": 5000,
        "ilndExchRtpChrYn": "Y",
        "ilndRtpAmt": 5000,
        "ilndExchAmt": 5000,
        "jejuDlvPsblYn": "Y",
        "jejuChrDlvYn": "Y",
        "jejuChrDlvcAmt": 5000,
        "jejuExchRtpChrYn": "Y",
        "jejuRtpAmt": 5000,
        "jejuExchAmt": 5000,
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
        "prdBaseCmposCntnt": _truncate_prdnm(name),
        "orgprdPkgCnt": 1,
        "prdUnitValCd40": "A01",
        "prdUnitValCd20": "B01",
        # 환불유형 10=상품확인 후 환불, 20=즉시환불 → 상품확인 후 환불
        "rfnTypCd": 10,
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
            # 정보고시 — 의류 코드 1001~1009. 수집데이터(소재·색상·제조자·제조국 등) 우선,
            # 없으면 "상품 페이지 참조" 기본값.
            "prdGovPublsItmList": gs.get("prdGovPublsItmList")
            or _build_gov_publs(
                product, brand, category_prd_cls_cd or str(gs.get("prdClsCd") or "")
            ),
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

    async def _resolve_category(
        self, session: Any, product: dict[str, Any], category_id: str, account: Any
    ) -> str:
        """매핑이 없으면 소싱 카테고리로 prdClsCd|sectId 자동매칭.
        베이스 handle()의 '카테고리 코드 없음' 검증 전에 호출되어 자동매칭이 통한다.
        """
        return await _resolve_gs_category_id(session, product, category_id)

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

        # 카테고리 자동결정 — 보통 베이스 handle()의 _resolve_category 훅에서 이미 매칭됨.
        # execute()를 직접 호출하는 경로(테스트 등) 대비 한 번 더 폴백 처리.
        category_id = await _resolve_gs_category_id(session, product, category_id)

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

        # 계정 설정 반품/교환비 fallback (정책 gsSettings에 없을 때).
        # returnFee/exchangeFee는 계정 additional_fields에 저장되는데 auth_creds 출처가
        # 설정/resolver일 때 누락될 수 있어, 계정 additional_fields도 함께 조회한다.
        _acct_extra = (
            getattr(account, "additional_fields", None) or {} if account else {}
        )
        if not gs_settings.get("rtpAmt"):
            _rf = auth_creds.get("returnFee") or _acct_extra.get("returnFee")
            if _rf:
                gs_settings = {**gs_settings, "rtpAmt": int(_rf)}
        if not gs_settings.get("exchAmt"):
            _ef = auth_creds.get("exchangeFee") or _acct_extra.get("exchangeFee")
            if _ef:
                gs_settings = {**gs_settings, "exchAmt": int(_ef)}

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
