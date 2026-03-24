"""SSG(신세계몰) Open API 클라이언트 - 상품 등록/수정.

인증 방식: Authorization 헤더에 업체 인증키
기본 URL: https://eapi.ssgadm.com

API 버전:
- 조회(GET): 0.1 (브랜드, 카테고리 등)
- 등록/수정(POST): 0.5 (insertItem, updateItem)
- 주소: 0.3
- 상품관리속성: 0.1~0.2

사이트번호:
- 6001: 이마트몰
- 6004: 신세계몰
- 6009: 신세계백화점몰

API 경로 패턴:
- 업체정보: /venInfo/{version}/xxx.ssg
- 상품관리: /item/{version}/xxx.ssg
- 공통정보: /common/{version}/xxx.ssg

JSON 구조 주의: SSG는 XStream 기반이므로 배열을
요소명 래퍼로 감싸야 함.
  예) "sites": [{"siteNo":"6004"}]  (X)
      "sites": {"site": {"siteNo":"6004"}}  (O)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from backend.core.config import settings
from backend.utils.logger import logger


class SSGClient:
  """SSG Open API 클라이언트."""

  BASE_URL = "https://eapi.ssgadm.com"

  def __init__(self, api_key: str, site_no: str = "6004") -> None:
    """api_key: 업체 인증키, site_no: 사이트번호 (기본 신세계몰)."""
    self.api_key = api_key
    self.site_no = site_no

  def _headers(self, accept: str = "application/json") -> dict[str, str]:
    return {
      "Authorization": self.api_key,
      "Content-Type": "application/json",
      "Accept": accept,
    }

  async def _call_api(
    self,
    method: str,
    path: str,
    body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, str]] = None,
  ) -> dict[str, Any]:
    """공통 API 호출.

    SSG는 에러 시 HTTP 500을 반환하면서도 JSON body에 에러 내용을 담으므로
    500 응답도 JSON 파싱 후 반환한다.
    """
    url = f"{self.BASE_URL}{path}"
    headers = self._headers()

    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      if method == "GET":
        resp = await client.get(url, headers=headers, params=params)
      elif method == "POST":
        resp = await client.post(url, headers=headers, json=body or {})
      elif method == "PUT":
        resp = await client.put(url, headers=headers, json=body or {})
      elif method == "DELETE":
        resp = await client.delete(url, headers=headers, params=params)
      else:
        raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

      try:
        data = resp.json()
      except Exception:
        data = {"raw": resp.text}

      logger.info(f"[SSG] {method} {path} → {resp.status_code}")

      # SSG는 500 응답에도 JSON 에러를 담아 보냄 — 에러 내용 추출
      if not resp.is_success:
        # SSG JSON 에러 응답에서 상세 메시지 추출
        result_obj = data.get("result", {}) if isinstance(data, dict) else {}
        desc = ""
        if isinstance(result_obj, dict):
          desc = result_obj.get("resultDesc", "") or result_obj.get("resultMessage", "")
        msg = desc or data.get("message", "") or data.get("msg", "") or resp.text[:300]
        raise SSGApiError(f"HTTP {resp.status_code}: {msg}")

      return data

  # ------------------------------------------------------------------
  # 인증 테스트
  # ------------------------------------------------------------------

  async def test_auth(self) -> dict[str, Any]:
    """인증 테스트 — 브랜드 목록 조회로 키 유효성 확인."""
    result = await self._call_api(
      "GET", "/venInfo/0.1/listBrand.ssg"
    )
    return {"success": True, "message": "인증 성공", "data": result}

  # ------------------------------------------------------------------
  # 상품 등록/수정/조회
  # ------------------------------------------------------------------

  async def register_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
    """상품 등록 — insertItem 래퍼 자동 적용.

    SSG Open API: POST /item/0.5/insertItem.ssg
    """
    body = {"insertItem": product_data}
    result = await self._call_api(
      "POST",
      "/item/0.5/insertItem.ssg",
      body=body,
    )
    return {"success": True, "data": result}

  async def update_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
    """상품 수정."""
    body = {"updateItem": product_data}
    result = await self._call_api(
      "POST",
      "/item/0.5/updateItem.ssg",
      body=body,
    )
    return {"success": True, "data": result}

  async def delete_product(self, item_id: str) -> dict[str, Any]:
    """상품 삭제 (리스트에서 완전 제거)."""
    body = {"deleteItem": {"itemId": item_id}}
    result = await self._call_api(
      "POST",
      "/item/0.5/deleteItem.ssg",
      body=body,
    )
    return {"success": True, "data": result}

  async def get_product(self, item_id: str) -> dict[str, Any]:
    """상품 조회."""
    return await self._call_api(
      "GET",
      "/item/0.1/getItemList.ssg",
      params={"itemId": item_id},
    )

  # ------------------------------------------------------------------
  # 업체정보 조회
  # ------------------------------------------------------------------

  async def get_brands(self, keyword: str = "") -> dict[str, Any]:
    """브랜드 목록 조회."""
    params: dict[str, str] = {}
    if keyword:
      params["brandNm"] = keyword
    return await self._call_api("GET", "/venInfo/0.1/listBrand.ssg", params=params or None)

  async def get_categories(self, std_ctg_id: str = "") -> dict[str, Any]:
    """표준카테고리 조회."""
    params: dict[str, str] = {}
    if std_ctg_id:
      params["stdCtgId"] = std_ctg_id
    return await self._call_api("GET", "/venInfo/0.1/listStdCtg.ssg", params=params or None)

  async def get_shipping_policies(self) -> dict[str, Any]:
    """배송비정책 목록 조회."""
    return await self._call_api("GET", "/venInfo/0.1/listShppcstPlcy.ssg")

  async def get_addresses(self) -> dict[str, Any]:
    """출고/반품 주소 목록 조회 (v0.3 필수)."""
    return await self._call_api("GET", "/venInfo/0.3/listVenAddr.ssg")

  async def fetch_infra(self) -> dict[str, str]:
    """상품 등록에 필요한 인프라 ID 자동 조회.

    반환: whoutShppcstId, retShppcstId, whoutAddrId, snbkAddrId
    """
    infra: dict[str, str] = {}

    # 배송비정책 조회
    try:
      sp = await self.get_shipping_policies()
      policies = sp.get("result", {}).get("shppcstPlcys", [{}])
      policy_list = policies[0].get("shppcstPlcy", []) if policies else []

      for p in policy_list:
        div = p.get("shppcstPlcyDivCd")
        sid = p.get("shppcstId", "")
        # 10=출고(일반배송), 20=반품
        if div == 10 and "whoutShppcstId" not in infra:
          infra["whoutShppcstId"] = sid
        elif div == 20 and "retShppcstId" not in infra:
          infra["retShppcstId"] = sid
    except Exception as exc:
      logger.warning(f"[SSG] 배송비정책 조회 실패: {exc}")

    # 주소 조회
    try:
      addr = await self.get_addresses()
      addr_list = addr.get("result", {}).get("venAddrDelInfo", [{}])
      addrs = addr_list[0].get("venAddrDelInfoDto", []) if addr_list else []

      # 기본주소(bascAddrYn=Y) 우선, 없으면 첫 번째 사용
      base_addr = next((a for a in addrs if a.get("bascAddrYn") == "Y"), None)
      if not base_addr and addrs:
        base_addr = addrs[0]

      if base_addr:
        addr_id = base_addr.get("grpAddrId", "")
        infra["whoutAddrId"] = addr_id
        infra["snbkAddrId"] = addr_id
    except Exception as exc:
      logger.warning(f"[SSG] 주소 조회 실패: {exc}")

    return infra

  # ------------------------------------------------------------------
  # 계약 브랜드 매핑 (brandNm → brandId)
  # ------------------------------------------------------------------

  # SSG 계약 브랜드 목록 — 키: 매칭용 소문자, 값: (brandId, 표시명)
  CONTRACTED_BRANDS: dict[str, tuple[str, str]] = {
    "게스": ("2000002737", "게스"),
    "guess": ("2000002737", "게스"),
    "나이키": ("2000004827", "나이키"),
    "nike": ("2000004827", "나이키"),
    "노스페이스": ("2000006637", "노스페이스"),
    "the north face": ("2000006637", "노스페이스"),
    "northface": ("2000006637", "노스페이스"),
    "뉴발란스": ("2011015410", "뉴발란스"),
    "new balance": ("2011015410", "뉴발란스"),
    "스노우피크": ("2011000375", "스노우피크"),
    "snow peak": ("2011000375", "스노우피크"),
    "snowpeak": ("2011000375", "스노우피크"),
    "스케쳐스": ("2000006059", "스케쳐스"),
    "skechers": ("2000006059", "스케쳐스"),
    "아디다스": ("2000000507", "아디다스"),
    "adidas": ("2000000507", "아디다스"),
    "에코": ("2011012514", "에코"),
    "ecco": ("2011012514", "에코"),
    "잔스포츠": ("2000020559", "잔스포츠"),
    "jansport": ("2000020559", "잔스포츠"),
    "지포어": ("3000020249", "지포어"),
    "g/fore": ("3000020249", "지포어"),
    "gfore": ("3000020249", "지포어"),
    "코오롱스포츠": ("2000003676", "코오롱스포츠"),
    "kolon sport": ("2000003676", "코오롱스포츠"),
    "크레모아": ("3000006049", "크레모아"),
    "claymore": ("3000006049", "크레모아"),
    "푸마": ("2000005405", "푸마"),
    "puma": ("2000005405", "푸마"),
    "휠라": ("2000002338", "휠라"),
    "fila": ("2000002338", "휠라"),
  }

  @classmethod
  def match_brand(cls, brand_name: str) -> tuple[str, str]:
    """상품 브랜드명으로 SSG 계약 브랜드 매칭.

    반환: (brandId, 표시명). 매칭 실패 시 ("9999999999", "").
    """
    if not brand_name:
      return "9999999999", ""

    lower = brand_name.strip().lower()

    # 정확 매칭
    if lower in cls.CONTRACTED_BRANDS:
      return cls.CONTRACTED_BRANDS[lower]

    # 부분 매칭 (브랜드명이 상품 브랜드에 포함)
    for key, (bid, display) in cls.CONTRACTED_BRANDS.items():
      if key in lower or lower in key:
        return bid, display

    return "9999999999", ""

  @staticmethod
  def remove_brand_from_name(name: str, brand_display: str) -> str:
    """상품명에서 브랜드명 제거 (SSG 정책: 상품명에 브랜드명 포함 불가)."""
    if not brand_display or not name:
      return name

    import re
    # 한글 브랜드명 제거
    cleaned = re.sub(re.escape(brand_display), "", name, flags=re.IGNORECASE)
    # CONTRACTED_BRANDS에서 영문명도 찾아서 제거
    for key, (_, disp) in SSGClient.CONTRACTED_BRANDS.items():
      if disp == brand_display and key != brand_display.lower():
        cleaned = re.sub(re.escape(key), "", cleaned, flags=re.IGNORECASE)

    # 연속 공백 정리
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    # 앞뒤 특수문자 정리
    cleaned = re.sub(r"^[\s\-/]+|[\s\-/]+$", "", cleaned)
    return cleaned or name  # 빈 문자열이면 원래 이름 유지

  # ------------------------------------------------------------------
  # XStream JSON 변환 헬퍼
  # ------------------------------------------------------------------

  @staticmethod
  def _wrap_list(items: list[dict[str, Any]], element_name: str) -> dict[str, Any]:
    """XStream 호환: 배열을 요소명 래퍼로 감싸기.

    단일 항목이면 객체로, 복수 항목이면 배열로.
    예) [{"a":1}] → {"item": {"a":1}}
        [{"a":1},{"a":2}] → {"item": [{"a":1},{"a":2}]}
    """
    if len(items) == 1:
      return {element_name: items[0]}
    return {element_name: items}

  # ------------------------------------------------------------------
  # 상품 데이터 변환
  # ------------------------------------------------------------------

  def transform_product(
    self,
    product: dict[str, Any],
    category_id: str = "",
    brand_id: str = "",
    infra: Optional[dict[str, str]] = None,
  ) -> dict[str, Any]:
    """SambaCollectedProduct → SSG insertItem 요청 데이터 변환.

    XStream JSON 형식으로 변환하며, infra 딕셔너리에서
    배송비/주소 ID를 가져온다.
    """
    inf = infra or {}
    raw_name = (product.get("name", "") or "")[:100]
    sale_price = int(product.get("sale_price", 0) or 0)
    cost = int(product.get("cost", 0) or 0) or int(sale_price * 0.7)
    detail_html = product.get("detail_html", "") or f"<p>{raw_name}</p>"
    images = product.get("images") or []
    brand = product.get("brand", "")
    material = product.get("material", "") or "상세설명참조"
    color = product.get("color", "") or "상세설명참조"
    manufacturer = product.get("manufacturer", "") or brand or "상세설명참조"

    # 브랜드 매칭 (계약 브랜드 자동 탐색)
    matched_brand_id, matched_brand_name = self.match_brand(brand)
    if matched_brand_id == "9999999999" and manufacturer:
      # 브랜드 필드에 없으면 제조사로 재시도
      matched_brand_id, matched_brand_name = self.match_brand(manufacturer)
    if brand_id:
      matched_brand_id = brand_id  # 명시적 지정 우선

    # 상품명 — 브랜드 제거는 삭제어 기능에서 처리
    name = raw_name
    logger.info(f"[SSG] 브랜드 매칭: {brand} → {matched_brand_id}({matched_brand_name})")

    now = datetime.now(timezone.utc)
    disp_start = now.strftime("%Y%m%d")
    disp_end = "20991231"

    options = product.get("options") or []
    # SSG 마진율: 정수 퍼센트 (예: 10 = 10%)
    margin_pct = round((sale_price - cost) / sale_price * 100) if sale_price > 0 else 30

    # 배송/주소 ID
    whout_shppcst_id = inf.get("whoutShppcstId", "")
    ret_shppcst_id = inf.get("retShppcstId", "")
    whout_addr_id = inf.get("whoutAddrId", "")
    snbk_addr_id = inf.get("snbkAddrId", "")

    # ── 이미지 (XStream: itemImgs → imgInfo) ──
    item_imgs_list = []
    for idx, url in enumerate(images[:10]):
      item_imgs_list.append({
        "dataSeq": idx + 1,
        "dataFileNm": url,
        "rplcTextNm": name[:50] if idx == 0 else f"{name[:40]}_{idx + 1}",
      })

    # ── 상품관리속성 (카테고리별 동적 생성) ──
    from backend.domain.samba.proxy.notice_utils import build_ssg_notice
    item_mng_attrs_list = build_ssg_notice(product)

    data: dict[str, Any] = {
      # 기본 정보
      "itemNm": name,
      "brandId": matched_brand_id,
      "stdCtgId": category_id,

      # 사이트 (XStream 래핑)
      "sites": {"site": {"siteNo": self.site_no, "sellStatCd": "20"}},

      # 검색
      "srchPsblYn": "Y",
      "itemSrchwdNm": name[:100],

      # 상품 특성
      "itemChrctDivCd": "10",
      "exusItemDivCd": "10",
      "exusItemDtlCd": "10",

      # 상품관리속성 (XStream 래핑)
      "itemMngPropClsId": "0000000001",
      "itemMngAttrs": self._wrap_list(item_mng_attrs_list, "itemMngAttr"),

      # 제조사/원산지
      "manufcoNm": manufacturer,
      "prodManufCntryId": "1000000001",  # SSG 내부 국가코드

      # 전시카테고리 (XStream 래핑)
      "dispCtgs": {"dispCtg": {
        "siteNo": self.site_no,
        "dispCtgId": category_id,
      }} if category_id else None,

      "dispStrtDts": disp_start,
      "dispEndDts": disp_end,
      "sellUnitQty": 1,

      # 매입/과세
      "buyFrmCd": "60",  # 위수탁
      "txnDivCd": "30",  # 면세(의류 기본)

      # 가격 (XStream 래핑)
      "salesPrcInfos": {"uitemPrc": {
        "splprc": cost,
        "sellprc": sale_price,
        "mrgrt": margin_pct,
      }},

      # 재고
      "invMngYn": "Y",

      # 판매유형
      "itemSellTypeCd": "10",
      "itemSellTypeDtlCd": "10",

      # 배송
      "shppItemDivCd": "01",
      "shppMthdCd": "20",  # 택배
      "shppRqrmDcnt": 3,

      # 배송비/주소 ID (root level)
      "whoutShppcstId": whout_shppcst_id,
      "retShppcstId": ret_shppcst_id,
      "whoutAddrId": whout_addr_id,
      "snbkAddrId": snbk_addr_id,

      # 배송기준 (XStream 래핑 — v0.5 필수)
      "itemShppCritns": {"itemShppCritn": {
        "shppMainCd": "32",  # 업체창고
        "shppMthdCd": "20",
        "jejuShppDisabYn": "N",
        "ismtarShppDisabYn": "N",
        "whoutAddrId": whout_addr_id,
        "snbkAddrId": snbk_addr_id,
        "whoutShppcstId": whout_shppcst_id,
        "retShppcstId": ret_shppcst_id,
        "mareaShppYn": "Y",
      }},

      # 이미지 (XStream 래핑)
      "itemImgs": self._wrap_list(item_imgs_list, "imgInfo") if item_imgs_list else None,

      # 상세설명
      "itemDesc": detail_html,

      # 기타 필수
      "giftPsblYn": "N",
      "palimpItemYn": "N",
      "itemSellWayCd": "10",
      "itemStatTypeCd": "10",
      "whinNotiYn": "N",
    }

    # None 값 제거
    data = {k: v for k, v in data.items() if v is not None}

    # 단품(옵션) 추가
    if options:
      uitems_list = []
      uitem_prices_list = []
      for idx, opt in enumerate(options):
        opt_name = opt.get("name", "") or opt.get("size", "") or f"옵션{idx + 1}"
        opt_stock = opt.get("stock", 999)
        is_sold_out = opt.get("isSoldOut", False)
        temp_id = str(idx + 1)

        uitems_list.append({
          "tempUitemId": temp_id,
          "uitemOptnTypeNm1": "사이즈",
          "uitemOptnNm1": opt_name,
          "baseInvQty": 0 if is_sold_out else opt_stock,
          "useYn": "N" if is_sold_out else "Y",
        })
        uitem_prices_list.append({
          "tempUitemId": temp_id,
          "splprc": cost,
          "sellprc": sale_price,
          "mrgrt": margin_pct,
        })

      data["itemSellTypeCd"] = "20"  # 옵션상품
      data["uitemAttr"] = {
        "uitemCacOptnYn": "N",
        "uitemOptnChoiTypeCd1": "10",
        "uitemOptnExpsrTypeCd1": "10",
      }
      data["uitems"] = self._wrap_list(uitems_list, "uitem")
      data["uitemPluralPrcs"] = self._wrap_list(uitem_prices_list, "uitemPrc")

    return data


class SSGApiError(Exception):
  """SSG API 에러."""
  pass
