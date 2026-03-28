"""롯데ON Open API 클라이언트 - 상품 등록/수정.

인증 방식: Bearer {apiKey}
기본 URL: https://openapi.lotteon.com
카테고리/브랜드: https://onpick-api.lotteon.com (별도 도메인)

거래처 정보(trGrpCd, trNo)는 identity API에서 자동 획득.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

from backend.domain.samba.proxy.notice_utils import build_lotteon_notice as _build_lot_notice

import httpx

from backend.core.config import settings
from backend.utils.logger import logger


# ──────────────────────────────────────────────────────────────────────
# 원산지 → 롯데ON ISO alpha-2 코드 매핑
# ──────────────────────────────────────────────────────────────────────

_LOTTEON_ORIGIN_CODE: dict[str, str] = {
  # 국내
  "한국": "KR", "대한민국": "KR", "국내": "KR", "국산": "KR", "korea": "KR",
  # 아시아
  "중국": "CN", "china": "CN",
  "베트남": "VN", "vietnam": "VN",
  "일본": "JP", "japan": "JP",
  "인도": "IN", "india": "IN",
  "인도네시아": "ID", "indonesia": "ID",
  "태국": "TH", "thailand": "TH",
  "캄보디아": "KH", "cambodia": "KH",
  "방글라데시": "BD", "bangladesh": "BD",
  "미얀마": "MM", "myanmar": "MM",
  "필리핀": "PH", "philippines": "PH",
  "홍콩": "HK", "hong kong": "HK",
  "대만": "TW", "taiwan": "TW",
  "말레이시아": "MY", "malaysia": "MY",
  # 유럽
  "이탈리아": "IT", "italy": "IT",
  "프랑스": "FR", "france": "FR",
  "독일": "DE", "germany": "DE",
  "스페인": "ES", "spain": "ES",
  "영국": "GB", "uk": "GB",
  "포르투갈": "PT", "portugal": "PT",
  # 북미
  "미국": "US", "usa": "US", "us": "US",
  "캐나다": "CA", "canada": "CA",
}


def _get_lotteon_origin_code(origin: str) -> str:
  """원산지 텍스트 → 롯데ON ISO alpha-2 코드. 미매핑 시 KR 폴백."""
  if not origin:
    return "KR"
  lower = origin.lower().strip()
  if lower in _LOTTEON_ORIGIN_CODE:
    return _LOTTEON_ORIGIN_CODE[lower]
  for keyword, code in _LOTTEON_ORIGIN_CODE.items():
    if keyword in lower or keyword in origin:
      return code
  return "KR"


# ──────────────────────────────────────────────────────────────────────
# SEO 키워드 생성
# ──────────────────────────────────────────────────────────────────────

def _build_lotteon_keywords(product: dict[str, Any]) -> list[str]:
  """SEO 검색 키워드 빌드 — 최대 20개, 각 30자 이내.

  우선순위: seo_keywords → tags → 브랜드 → 카테고리 → 상품명 단어 분리
  """
  seen: set[str] = set()
  keywords: list[str] = []

  def _add(kw: str) -> None:
    kw = kw.strip()[:30]
    if kw and kw not in seen:
      seen.add(kw)
      keywords.append(kw)

  for kw in (product.get("seo_keywords") or []):
    _add(str(kw))
  for tag in (product.get("tags") or []):
    _add(str(tag))

  brand = product.get("brand", "")
  if brand:
    _add(brand)

  for cat_field in ("category1", "category2", "category3"):
    cat = product.get(cat_field, "")
    if cat:
      _add(cat)

  name = product.get("name", "")
  for word in re.split(r"[\s\[\]()（）,./·|]+", name):
    word = word.strip()
    if len(word) >= 2:
      _add(word)

  return keywords[:20]


# ──────────────────────────────────────────────────────────────────────
# 상품 소개문 자동 생성
# ──────────────────────────────────────────────────────────────────────

def _build_lotteon_intro(product: dict[str, Any]) -> str:
  """상품 소개문 자동 생성 — 최대 200자.

  "[브랜드] 상품명 | 카테고리 | 소재: OOO, 색상: OOO, 원산지: OOO"
  """
  parts: list[str] = []
  brand = product.get("brand", "")
  name = product.get("name", "")
  category = product.get("category2") or product.get("category1") or ""
  material = product.get("material", "")
  color = product.get("color", "")
  origin = product.get("origin", "")

  if brand:
    parts.append(f"[{brand}]")
  if name:
    parts.append(name)
  if category:
    parts.append(f"| {category}")

  details: list[str] = []
  if material:
    details.append(f"소재: {material}")
  if color:
    details.append(f"색상: {color}")
  if origin:
    details.append(f"원산지: {origin}")
  if details:
    parts.append("| " + ", ".join(details))

  return " ".join(parts)[:200]


# ──────────────────────────────────────────────────────────────────────
# 상품홍보문구 자동 생성
# ──────────────────────────────────────────────────────────────────────

_PROMO_PHRASE: dict[str, str] = {
  # 하의
  "바지": "편한바지", "팬츠": "편한바지", "청바지": "편한청바지", "반바지": "편한반바지",
  "레깅스": "슬림레깅스", "스커트": "예쁜스커트", "치마": "예쁜치마",
  # 상의
  "티셔츠": "편한티셔츠", "티": "편한티", "셔츠": "스타일리시셔츠",
  "맨투맨": "편한맨투맨", "후드": "편한후드", "니트": "포근한니트", "스웨터": "포근한스웨터",
  # 아우터
  "자켓": "트렌디자켓", "재킷": "트렌디재킷", "코트": "세련된코트",
  "패딩": "따뜻한패딩", "점퍼": "스타일점퍼", "집업": "편한집업",
  # 신발
  "스니커즈": "편한스니커즈", "운동화": "편한운동화", "신발": "편한신발",
  "슬리퍼": "편한슬리퍼", "샌들": "시원한샌들", "구두": "세련된구두",
  # 가방
  "가방": "세련된가방", "백팩": "실용적백팩", "숄더백": "예쁜숄더백", "크로스백": "편한크로스백",
  # 기타
  "원피스": "우아한원피스", "수영복": "멋진수영복", "언더웨어": "편한언더웨어",
}


def _build_lotteon_promo(product: dict[str, Any]) -> str:
  """상품홍보문구 자동 생성 — '{브랜드} {카테고리문구}' 형식, 75바이트 이내.

  예: '아디다스 편한바지', '나이키 편한스니커즈'
  """
  brand = product.get("brand", "") or ""
  # category2(소분류) 우선, 없으면 category1(대분류)
  cat_raw = (product.get("category2") or product.get("category1") or "").strip()

  # 카테고리 키워드로 문구 매핑 (부분 일치)
  phrase = ""
  for keyword, mapped in _PROMO_PHRASE.items():
    if keyword in cat_raw:
      phrase = mapped
      break
  if not phrase:
    phrase = cat_raw  # 매핑 없으면 카테고리명 그대로

  parts = [p for p in [brand, phrase] if p]
  text = " ".join(parts)

  # 75바이트 이내로 자르기
  encoded = text.encode('utf-8')
  if len(encoded) > 75:
    text = encoded[:75].decode('utf-8', errors='ignore').rstrip()

  return text


# ──────────────────────────────────────────────────────────────────────
# 배송/반품 안내 HTML (epnLst NOTI 항목)
# ──────────────────────────────────────────────────────────────────────

def _build_delivery_notice_html(return_fee: int = 0, exchange_fee: int = 0) -> str:
  """배송·반품·교환 안내 HTML."""
  ret_txt = f"{return_fee:,}원" if return_fee else "정책에 따름"
  exc_txt = f"{exchange_fee:,}원" if exchange_fee else "정책에 따름"
  return (
    "<div style='font-family:sans-serif;font-size:14px;line-height:1.8;'>"
    "<p><b>■ 배송 안내</b></p>"
    "<p>· 주문일 기준 2~3 영업일 이내 발송 (주말·공휴일 제외)</p>"
    "<p>· 배송사: CJ대한통운 (도서산간 지역은 추가 배송비 발생)</p>"
    "<p><b>■ 반품·교환 안내</b></p>"
    "<p>· 상품 수령 후 7일 이내 신청 가능</p>"
    f"<p>· 단순 변심 반품 배송비: {ret_txt} / 교환 배송비: {exc_txt}</p>"
    "<p>· 상품 불량·오배송은 판매자 부담으로 무료 반품</p>"
    "<p>· 착용·세탁·훼손·태그 제거 후에는 반품·교환 불가</p>"
    "</div>"
  )


# ──────────────────────────────────────────────────────────────────────
# SEO 이미지 파일명 생성
# ──────────────────────────────────────────────────────────────────────

def _make_lotteon_img_filename(brand: str, name: str, idx: int, url: str) -> str:
  """브랜드·상품명 기반 SEO 파일명 생성. 확장자는 원본 URL에서 추출."""
  # 확장자 추출
  path = urlparse(url).path
  ext = path.rsplit(".", 1)[-1].lower() if "." in path else "jpg"
  if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
    ext = "jpg"

  # 슬러그 생성: 브랜드+상품명, 특수문자 → 하이픈
  slug_base = f"{brand}-{name}" if brand else name
  slug = re.sub(r"[^\w가-힣a-zA-Z0-9]", "-", slug_base)
  slug = re.sub(r"-{2,}", "-", slug).strip("-")[:80]
  return f"{slug}-{idx + 1:02d}.{ext}"


class LotteonClient:
  """롯데ON Open API 클라이언트."""

  BASE_URL = "https://openapi.lotteon.com"
  # 카테고리/브랜드는 별도 도메인
  ONPICK_URL = "https://onpick-api.lotteon.com"
  # 롯데홈쇼핑 주문 API (별도 시스템 — subscriptionId 인증, XML 응답)
  IMALL_URL = "https://openapi.lotteimall.com"

  def __init__(self, api_key: str) -> None:
    self.api_key = api_key
    self.tr_grp_cd: str = ""
    self.tr_no: str = ""

  def _headers(self) -> dict[str, str]:
    return {
      "Authorization": f"Bearer {self.api_key}",
      "Content-Type": "application/json;charset=UTF-8",
      "Accept": "application/json",
      "Accept-Language": "ko",
      "X-Timezone": "GMT+09:00",
    }

  async def _call_api(
    self,
    method: str,
    path: str,
    body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, str]] = None,
    base_url: Optional[str] = None,
    _shared_client: Optional[Any] = None,
  ) -> dict[str, Any]:
    """공통 API 호출. _shared_client 제공 시 TCP 연결 재사용."""
    url = f"{base_url or self.BASE_URL}{path}"
    headers = self._headers()

    async def _do(c: Any) -> Any:
      if method == "GET":
        return await c.get(url, headers=headers, params=params)
      elif method == "POST":
        return await c.post(url, headers=headers, json=body or {})
      elif method == "PUT":
        return await c.put(url, headers=headers, json=body or {})
      elif method == "DELETE":
        return await c.delete(url, headers=headers, params=params)
      raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

    if _shared_client is not None:
      resp = await _do(_shared_client)
    else:
      async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
        resp = await _do(client)

    try:
      data = resp.json()
    except Exception:
      data = {"raw": resp.text}

    logger.info(f"[롯데ON] {method} {path} → {resp.status_code}")

    if not resp.is_success:
      msg = data.get("message", "") or data.get("msg", "") or resp.text[:200]
      raise LotteonApiError(f"HTTP {resp.status_code}: {msg}")

    # HTTP 200이어도 응답 body에 에러 코드가 있을 수 있음
    # returnCode: 요청 레벨 에러 (카테고리 누락 등)
    res_code = (
      data.get("returnCode") or data.get("code")
      or data.get("resultCode") or data.get("rspnCd") or ""
    )
    if res_code and res_code not in ("0000", "00", "SUCCESS"):
      msg = data.get("message", "") or data.get("msg", "") or data.get("rspnMsgCntn", "") or str(data)
      logger.warning(f"[롯데ON] 응답 에러 코드: {res_code} — {msg}")
      logger.warning(f"[롯데ON] 응답 전체 body: {data}")
      raise LotteonApiError(f"응답 에러 ({res_code}): {msg}")

    return data

  async def _call_imall_api(self, path: str, params: dict[str, str]) -> str:
    """롯데홈쇼핑 주문 API 호출 (XML 응답).

    인증: subscriptionId URL 파라미터 (Bearer 토큰 아님).
    반환: XML 원문 문자열

    롯데홈쇼핑 Open API는 상태 변경 작업(반품승인, CS답변)도 GET 방식으로 파라미터를 전달하는 구조.
    (API 명세: openapitst.lotteimall.com 문서 기준)
    """
    # subscriptionId 자동 주입
    merged_params = {"subscriptionId": self.api_key, **params}
    url = f"{self.IMALL_URL}{path}"

    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      resp = await client.get(url, params=merged_params)

    logger.info(f"[롯데홈쇼핑] GET {path} → {resp.status_code}")

    if not resp.is_success:
      raise LotteonApiError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    text = resp.text

    # XML 바디 레벨 에러 확인 (HTTP 200이어도 에러 포함 가능)
    try:
      root = ET.fromstring(text)
      err_code = root.findtext("ReturnCode") or root.findtext("ErrorCode") or ""
      if err_code and err_code not in ("0000", "0001", ""):
        logger.warning(f"[롯데홈쇼핑] XML 에러 코드: {err_code} | {path}")
    except ET.ParseError:
      pass  # XML 파싱 실패는 _parse_xml_list에서 처리

    return text

  def _parse_xml_list(self, xml_text: str, item_tag: str) -> list[dict[str, str]]:
    """XML에서 item_tag 반복 요소를 dict 리스트로 변환.

    각 <item_tag> 하위 요소를 {태그명: 텍스트} dict로 변환.
    CDATA 및 None 값은 빈 문자열로 처리.
    """
    try:
      root = ET.fromstring(xml_text)
    except ET.ParseError as e:
      raise LotteonApiError(f"XML 파싱 실패: {e}") from e

    result: list[dict[str, str]] = []
    for item in root.iter(item_tag):
      row: dict[str, str] = {}
      for child in item:
        row[child.tag] = child.text or ""
      result.append(row)
    return result

  def _date_range(self, days: int) -> tuple[str, str]:
    """최근 N일 start_date, end_date 반환 (YYYYMMDD 형식)."""
    today = date.today()
    start = today - timedelta(days=days)
    return start.strftime("%Y%m%d"), today.strftime("%Y%m%d")

  # ------------------------------------------------------------------
  # 인증
  # ------------------------------------------------------------------

  async def test_auth(self) -> dict[str, Any]:
    """거래처 정보 조회 (인증 테스트) — trGrpCd, trNo 자동 획득."""
    result = await self._call_api("GET", "/v1/openapi/common/v1/identity")
    data = result.get("data", {})
    if data:
      self.tr_grp_cd = data.get("trGrpCd", "")
      self.tr_no = data.get("trNo", "")
    return {"success": True, "message": "인증 성공", "data": data}

  # ------------------------------------------------------------------
  # 상품 등록/수정/조회
  # ------------------------------------------------------------------

  async def register_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
    """상품 등록.

    롯데ON은 returnCode=0000(요청 접수)이어도
    data[].resultCode=9999이면 개별 상품 등록 실패.
    """
    result = await self._call_api(
      "POST",
      "/v1/openapi/product/v1/product/registration/request",
      body=product_data,
    )
    # 개별 상품 결과 검증 (data는 리스트)
    data_list = result.get("data", [])
    if isinstance(data_list, list) and data_list:
      item = data_list[0]
      if isinstance(item, dict):
        item_code = item.get("resultCode", "")
        if item_code and item_code not in ("0000", "00", "SUCCESS"):
          msg = item.get("resultMessage", "") or str(item)
          logger.warning(f"[롯데ON] 상품 등록 실패: {item_code} — {msg}")
          raise LotteonApiError(f"상품 등록 실패 ({item_code}): {msg}")
        # 성공 시 spdNo 추출
        spd_no = item.get("spdNo") or item.get("epdNo") or ""
        return {"success": True, "data": result, "spdNo": spd_no}
    return {"success": True, "data": result}

  async def update_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
    """승인 상품 수정.

    등록과 동일하게 data[].resultCode 검증 필요.
    """
    result = await self._call_api(
      "POST",
      "/v1/openapi/product/v1/product/modification/request",
      body=product_data,
    )
    # 개별 상품 결과 검증
    data_list = result.get("data", [])
    if isinstance(data_list, list) and data_list:
      item = data_list[0]
      if isinstance(item, dict):
        item_code = item.get("resultCode", "")
        if item_code and item_code not in ("0000", "00", "SUCCESS"):
          msg = item.get("resultMessage", "") or str(item)
          logger.warning(f"[롯데ON] 상품 수정 실패: {item_code} — {msg}")
          raise LotteonApiError(f"상품 수정 실패 ({item_code}): {msg}")
        spd_no = item.get("spdNo") or item.get("epdNo") or ""
        return {"success": True, "data": result, "spdNo": spd_no}
    return {"success": True, "data": result}

  async def get_product(self, spd_no: str) -> dict[str, Any]:
    """상품 단건 조회 (POST 방식)."""
    body = {
      "trGrpCd": self.tr_grp_cd or "SR",
      "trNo": self.tr_no,
      "spdNo": spd_no,
    }
    return await self._call_api(
      "POST",
      "/v1/openapi/product/v1/product/detail",
      body=body,
    )

  # ── 프로모션 API ───────────────────────────────────────────────────

  async def save_product_exception(self, spd_no: str, flags: dict[str, str]) -> dict[str, Any]:
    """행사 제외 설정.

    flags 예시:
      ownrDscExYn: Y/N    오너스할인 제외
      pdUtCpnExYn: Y/N    상품단위쿠폰 제외
      dvCpnExYn: Y/N      배송쿠폰 제외
      cmPcsDscExYn: Y/N   가격비교채널할인(CM+PCS) 제외
      pcsDscExYn: Y/N     가격비교(PCS)할인 제외
    """
    body = {"spdNo": spd_no, **flags}
    return await self._call_api(
      "POST",
      "/v1/openapi/promotion/v1/OpenApiService/saveProductException",
      body=body,
    )

  async def save_immediate_discount(
    self,
    spd_no: str,
    discount_rate: int,
    is_update: bool = False,  # 현재 미사용, 향후 기존 할인 수정 시 활용
  ) -> dict[str, Any]:
    """판매자할인(스토어할인) 저장.

    API 스펙:
      saveDvsCd: C=등록, U=수정(종료일만), D=삭제(시작 전만)
      afflPrNo: 셀러 자체 프로모션번호(PK, 중복 불가)
      dcTypCd: FX=정율, FL=정액
      aplyStrtDttm / aplyEndDttm: yyyymmddhhmiss 포맷
    """
    now = datetime.now()
    # afflPrNo: 셀러 고유 프로모션번호 (최대 20자)
    # spdNo 숫자 부분(≤12자) + timestamp 끝 8자 = 최대 20자 이내
    spd_num = re.sub(r"[^0-9]", "", spd_no)[-12:]  # 숫자만 추출, 최대 12자
    ts_suffix = str(int(now.timestamp()))[-8:]       # timestamp 끝 8자리
    affil_pr_no = f"{spd_num}{ts_suffix}"            # 최대 20자
    start_dt = now.strftime("%Y%m%d%H%M%S")
    # 1년 후 종료 (포맷: yyyymmddhhmiss)
    end_dt = (now.replace(year=now.year + 1)).strftime("%Y%m%d235959")
    body = {
      "saveDvsCd": "C",                            # 항상 신규 등록 (U=수정은 awyDcPdRegNo 필요)
      "awyDcPdRegNo": "",                          # 신규 등록 시 빈값
      "afflPrNo": affil_pr_no,                      # 셀러 자체 프로모션번호(PK)
      "trNo": self.tr_no,                           # 롯데ON 거래처번호
      "spdNo": spd_no,
      "aplyStrtDttm": start_dt,
      "aplyEndDttm": end_dt,
      "dcTypCd": "FX",                              # FX=정율, FL=정액
      "dcVal": float(discount_rate),
    }
    logger.info(f"[롯데ON] 즉시할인 요청 body: {body}")
    return await self._call_api(
      "POST",
      "/v1/openapi/promotion/v1/OpenApiService/saveProductImmediateDiscount",
      body=body,
    )

  async def save_lpoint_accumulation(
    self,
    spd_no: str,
    accm_val1: int = 0,
    accm_vp_knd_cd: str = "7",
    accm_val2: int = 0,
    accm_val3: int = 0,
    accm_val4: int = 0,
  ) -> dict[str, Any]:
    """L.POINT 추가적립 저장.

    API 스펙:
      cndAccmVal1: 구매확정시 L.POINT (>0이면 accmVpKndCd 필수)
      accmVpKndCd: 발송일로부터 N일 이내 구매확정 시 적립 (3~8 중 택1)
      cndAccmVal2/3/4: 리뷰/사진/동영상 포인트 (하이마트/홈쇼핑 전용, 일반은 0)
    """
    now = datetime.now()
    spd_num = re.sub(r"[^0-9]", "", spd_no)[-12:]
    ts_suffix = str(int(now.timestamp()))[-8:]
    affil_pr_no = f"{spd_num}{ts_suffix}"
    start_dt = now.strftime("%Y%m%d%H%M%S")
    end_dt = (now.replace(year=now.year + 1)).strftime("%Y%m%d235959")
    body = {
      "saveDvsCd": "C",
      "accmPdRegNo": "",
      "afflPrNo": affil_pr_no,
      "trNo": self.tr_no,
      "aplyStrtDttm": start_dt,
      "aplyEndDttm": end_dt,
      "spdNo": spd_no,
      "cndAccmVal1": accm_val1,
      "accmVpKndCd": accm_vp_knd_cd,
      "cndAccmVal2": accm_val2,
      "cndAccmVal3": accm_val3,
      "cndAccmVal4": accm_val4,
    }
    logger.info(f"[롯데ON] L.POINT 적립 요청 body: {body}")
    return await self._call_api(
      "POST",
      "/v1/openapi/promotion/v1/OpenApiService/saveProductLPoint",
      body=body,
    )

  async def search_quantity_discount_list(self, spd_no: str) -> dict[str, Any]:
    """살수록할인 목록 조회 — 기존 프로모션 prNo 확인용.

    반환 data 예시:
      {"prList": [{"prNo": "12345", "prNm": "...", ...}]}
    """
    return await self._call_api(
      "POST",
      "/v1/openapi/promotion/v1/OpenApiService/searchQuantityDiscountList",
      body={"spdNo": spd_no, "prKndCd": "PRD_MAM_BUY"},
    )

  async def insert_quantity_discount(
    self,
    spd_no: str,
    min_qty: int,
    discount_rate: float,
    eitm_nos: list[str] | None = None,
    pr_no: str = "",
  ) -> dict[str, Any]:
    """살수록할인(수량 기준 정율 할인) 등록/수정.

    API 스펙:
      saveDvsCd: C=신규, U=수정(pr_no 필수), D=삭제(pr_no 필수)
      prKndCd: PRD_MAM_BUY (살수록/배수할인)
      fvrOffrValDvsDtlCd: QTY_DC (수량 기준 할인)
      dcTypCd: FX=정율, FL=정액
      dcQtyList[].minPurQty: 최소 구매수량
      dcQtyList[].dcRt: 할인율 (정율일 때)
      dcQtyList[].dcAmt: 할인액 (정액일 때, 정율이면 0)
      spdList[].spdNo: 적용 상품번호
    """
    now = datetime.now()
    spd_num = re.sub(r"[^0-9]", "", spd_no)[-12:]
    ts_suffix = str(int(now.timestamp()))[-8:]
    affil_pr_no = f"{spd_num}{ts_suffix}"  # 최대 20자
    start_dt = now.strftime("%Y%m%d%H%M%S")
    end_dt = (now.replace(year=now.year + 1)).strftime("%Y%m%d235959")
    save_dvs_cd = "U" if pr_no else "C"
    body = {
      "saveDvsCd": save_dvs_cd,                 # C=신규, U=수정
      "prKndCd": "PRD_MAM_BUY",                 # 살수록/배수할인
      "prNo": pr_no,                             # 수정 시 기존 prNo, 신규 시 빈값
      "prNm": "삼바 살수록할인",
      "afflPrNo": affil_pr_no,                   # 셀러 자체 프로모션번호(PK, 최대 20자)
      "trNo": self.tr_no,
      "aplyStrtDttm": start_dt,
      "aplyEndDttm": end_dt,
      "fvrOffrValDvsDtlCd": "QTY_DC",           # 수량 기준 할인
      "dcTypCd": "FX",                           # 정율 할인
      "dcQtyList": [
        {
          "minPurQty": int(min_qty),             # 최소 구매수량
          "dcAmt": 0,                            # 정액할인액 (정율이므로 0)
          "dcRt": float(discount_rate),          # 할인율 (%)
        }
      ],
      "spdList": (
        [{"spdNo": spd_no, "sitmNo": eitm_no} for eitm_no in eitm_nos]
        if eitm_nos else
        [{"spdNo": spd_no, "sitmNo": ""}]        # eitm_nos 없을 때 폴백
      ),
    }
    logger.info(f"[롯데ON] 살수록할인 요청 body: {body}")
    return await self._call_api(
      "POST",
      "/v1/openapi/promotion/v1/OpenApiService/insertQuantityDiscount",
      body=body,
    )

  async def update_stock(self, itm_stk_lst: list[dict[str, Any]]) -> dict[str, Any]:
    """단품 재고 변경."""
    return await self._call_api(
      "POST",
      "/v1/openapi/product/v1/item/stock/change",
      body={"itmStkLst": itm_stk_lst},
    )

  async def update_price(self, itm_prc_lst: list[dict[str, Any]]) -> dict[str, Any]:
    """단품 가격 변경."""
    return await self._call_api(
      "POST",
      "/v1/openapi/product/v1/item/price/change",
      body={"itmPrcLst": itm_prc_lst},
    )

  async def change_status(self, spd_lst: list[dict[str, Any]]) -> dict[str, Any]:
    """상품 판매상태 변경 (slStatCd: SALE | SOUT | END).

    trGrpCd/trNo는 등록/수정 API와 동일하게 spdLst 각 아이템 안에 위치해야 함.
    """
    enriched = [
      {"trGrpCd": self.tr_grp_cd or "SR", "trNo": self.tr_no, **item}
      for item in spd_lst
    ]
    body: dict[str, Any] = {"spdLst": enriched}
    logger.info(f"[롯데ON] change_status 요청 body: {body}")
    return await self._call_api(
      "POST",
      "/v1/openapi/product/v1/product/status/change",
      body=body,
    )

  async def delete_product(self, spd_no: str) -> dict[str, Any]:
    """상품 삭제 (리스트에서 완전 제거)."""
    result = await self._call_api(
      "POST",
      "/v1/openapi/product/v1/product/delete",
      body={"spdLst": [{"spdNo": spd_no, "selPrdNo": spd_no}]},
    )
    return {"success": True, "data": result}

  # ------------------------------------------------------------------
  # 카테고리 / 브랜드 (onpick-api 도메인)
  # ------------------------------------------------------------------

  async def get_categories(
    self,
    cat_id: str = "",
    depth: str = "",
    parent_id: str = "",
    skip: int = 0,
    limit: int = 500,
    _shared_client: Optional[Any] = None,
  ) -> dict[str, Any]:
    """표준카테고리 조회 (onpick-api 도메인).

    Args:
      cat_id: filter_1 — 특정 카테고리 ID 조회
      depth: filter_3 — 뎁스 레벨 (1~4)
      parent_id: filter_2 — 부모 카테고리 ID로 하위 목록 조회
      skip: 페이지네이션 시작 위치
      limit: 페이지당 건수 (최대 500)
      _shared_client: 대량 조회 시 TCP 연결 재사용용 httpx 클라이언트
    """
    params: dict[str, str] = {
      "job": "cheetahStandardCategory",
      "skip": str(skip),
      "limit": str(limit),
    }
    if cat_id:
      params["filter_1"] = cat_id
    if parent_id:
      params["filter_2"] = parent_id
    if depth:
      params["filter_3"] = depth
    return await self._call_api(
      "GET",
      "/cheetah/econCheetah.ecn",
      params=params,
      base_url=self.ONPICK_URL,
      _shared_client=_shared_client,
    )

  async def get_delivery_zones(self) -> dict[str, Any]:
    """배송권역 그룹 목록 조회."""
    return await self._call_api(
      "GET",
      "/v1/openapi/delivery/v1/zone/group/list",
    )

  async def get_category_attributes(self, scat_no: str) -> dict[str, Any]:
    """표준카테고리 속성목록 조회 (onpick-api 도메인).

    scatAttrLst 구성에 필요한 optCd / optValCd 조회.
    """
    return await self._call_api(
      "GET",
      "/cheetah/econCheetah.ecn",
      params={"job": "cheetahScatAttr", "mf_1": scat_no},
      base_url=self.ONPICK_URL,
    )

  async def get_category_attributes_by_job(self, job: str, scat_no: str, param_key: str = "mf_1") -> dict[str, Any]:
    """표준카테고리 속성목록 조회 — job명/param키 탐색용."""
    return await self._call_api(
      "GET",
      "/cheetah/econCheetah.ecn",
      params={"job": job, param_key: scat_no},
      base_url=self.ONPICK_URL,
    )

  async def get_category_attribute_list(self, category_id: str) -> dict[str, Any]:
    """표준카테고리 속성목록 조회 — 메인 API 경로 시도."""
    return await self._call_api(
      "GET",
      f"/v1/openapi/product/v1/category/attribute/list",
      params={"scatNo": category_id},
    )

  async def search_brand(self, keyword: str) -> dict[str, Any]:
    """브랜드 검색 (onpick-api 도메인)."""
    return await self._call_api(
      "GET",
      "/cheetah/econCheetah.ecn",
      params={"job": "cheetahBrnd", "mf_1": keyword},
      base_url=self.ONPICK_URL,
    )

  # ------------------------------------------------------------------
  # 상품 데이터 변환
  # ------------------------------------------------------------------

  @staticmethod
  def transform_product(
    product: dict[str, Any],
    category_id: str = "",
    tr_grp_cd: str = "SR",
    tr_no: str = "",
    disp_cat_id: str = "",
  ) -> dict[str, Any]:
    """SambaCollectedProduct → 롯데ON 상품 등록 데이터 변환.

    Args:
      category_id: 표준카테고리번호 (BC...)
      disp_cat_id: 전시카테고리번호 (FC...) — 없으면 category_id 사용
    """
    from backend.utils.logger import logger as _log

    # ── 이미지 URL 정규화 ──────────────────────────────────────
    def _normalize_url(url: str) -> str:
      if url.startswith("//"):
        return "https:" + url
      return url

    raw_images = product.get("images") or []
    images = [
      _normalize_url(u) for u in raw_images
      if u and (u.startswith("http") or u.startswith("//"))
    ][:10]
    _log.info(f"[롯데ON] 이미지: 원본 {len(raw_images)}개 → 정규화 {len(images)}개")

    # ── 기본 상품 정보 ──────────────────────────────────────────
    sale_price = int(product.get("sale_price", 0))
    name = (product.get("name", "") or "")[:150]
    brand = product.get("brand", "") or ""
    # 제조사: manufacturer → brand → "제조사 미확인" 순 폴백
    manufacturer = (
      product.get("manufacturer", "")
      or brand
      or "제조사 미확인"
    )
    style_code = product.get("style_code", "") or product.get("styleCode", "") or ""
    origin = product.get("origin", "") or ""

    # ── 할인율 적용 ─────────────────────────────────────────────
    discount_rate = product.get("_discount_rate", 0)
    if discount_rate:
      sale_price = int(sale_price * (1 - discount_rate / 100))

    # ── 재고 / 배송비 ───────────────────────────────────────────
    # _stock_quantity: 설정된 경우 상한선(cap)으로 동작
    max_stock = int(product.get("_stock_quantity") or 0)
    default_stock = max_stock if max_stock > 0 else 999
    return_fee = product.get("_return_fee", 0) or 0
    exchange_fee = product.get("_exchange_fee", 0) or 0
    jeju_fee = product.get("_jeju_fee", 0) or 0

    # ── 판매 기간 ───────────────────────────────────────────────
    now = datetime.now()
    sl_strt = now.strftime("%Y%m%d%H%M%S")
    sl_end = (now + timedelta(days=365)).strftime("%Y%m%d%H%M%S")

    # ── 옵션에서 사이즈/색상 추출 (고시정보용) ──────────────────
    options = product.get("options") or []
    sizes = [
      o.get("size", "") or o.get("name", "")
      for o in options
      if o.get("size") or o.get("name")
    ]
    size_text = (
      ", ".join(sorted(set(s for s in sizes if s)))[:200]
      or "상세페이지 참조"
    )
    db_color = product.get("color", "")
    color_part = ""
    if " - " in (product.get("name") or ""):
      color_part = product["name"].split(" - ", 1)[1].split("/")[0].strip()
    color_text = db_color or (color_part[:200] if color_part else "상세페이지 참조")

    # ── 이미지 파일 목록 (origFileNm, origImgFileNm 모두 URL 필수) ─
    pd_file_lst = [
      {
        "fileTypCd": "PD",
        "fileDvsCd": "WDTH",
        "origFileNm": url,
        "origImgFileNm": url,
      }
      for idx, url in enumerate(images)
    ]

    # ── 단품 이미지 목록 ────────────────────────────────────────
    itm_img_lst = [
      {
        "epsrTypCd": "IMG",
        "epsrTypDtlCd": "IMG_SQRE",
        "origFileNm": url,
        "origImgFileNm": url,
        "rprtImgYn": "Y" if idx == 0 else "N",
      }
      for idx, url in enumerate(images)
    ]

    # ── 옵션 타입 감지 ──────────────────────────────────────────
    def _detect_opt_nm(opt: dict[str, Any]) -> str:
      """옵션 타입 자동 감지 (색상/사이즈/기타)."""
      keys = set(opt.keys())
      if "color" in keys or any("color" in str(k).lower() for k in keys):
        return "색상"
      if "size" in keys or any("size" in str(k).lower() for k in keys):
        return "사이즈"
      val = opt.get("name", "") or opt.get("value", "") or ""
      size_keywords = {"S", "M", "L", "XL", "XXL", "XS", "FREE", "프리", "스몰", "라지"}
      if val.strip().upper() in size_keywords or val.replace(".", "").isdigit():
        return "사이즈"
      return "옵션"

    # ── 단품(옵션) 목록 ─────────────────────────────────────────
    itm_lst: list[dict[str, Any]] = []
    if options:
      # 상품 전체에서 optNm 한 번만 결정 (단품 간 불일치 시 9999 에러)
      product_opt_nm = _detect_opt_nm(options[0])
      for idx, opt in enumerate(options):
        opt_name = (
          opt.get("name", "") or opt.get("size", "") or opt.get("value", "")
          or f"옵션{idx + 1}"
        )
        raw_stock = opt.get("stock")
        if raw_stock is None or raw_stock == 0:
          opt_stock = default_stock
        elif max_stock > 0:
          # _stock_quantity 설정 시 상한선으로 cap
          opt_stock = min(int(raw_stock), max_stock)
        else:
          opt_stock = int(raw_stock)
        itm_lst.append({
          "eitmNo": f"OPT{idx}",
          "dpYn": "Y",
          "sortSeq": idx + 1,
          "itmOptLst": [{"optNm": product_opt_nm, "optVal": opt_name}],
          "itmImgLst": itm_img_lst,
          "slPrc": sale_price,
          "stkQty": opt_stock,
        })
    else:
      itm_lst.append({
        "eitmNo": "OPT0",
        "dpYn": "Y",
        "sortSeq": 1,
        "itmOptLst": [],
        "itmImgLst": itm_img_lst,
        "slPrc": sale_price,
        "stkQty": default_stock,
      })

    # ── 상세설명 ────────────────────────────────────────────────
    detail_html = product.get("detail_html", "") or f"<p>{name}</p>"

    # ── SEO: 검색 키워드 / 상품 소개문 ─────────────────────────
    keywords = _build_lotteon_keywords(product)
    intro = _build_lotteon_intro(product)

    # ── 고시정보 (실제 수집 데이터 주입) ───────────────────────
    notice = _build_lot_notice(
      product,
      size_text=size_text,
      color_text=color_text,
      mfr=manufacturer,
    )

    # ── 원산지 코드 동적 매핑 ───────────────────────────────────
    origin_code = _get_lotteon_origin_code(origin)

    spd: dict[str, Any] = {
      "trGrpCd": tr_grp_cd,
      "trNo": tr_no,
      "scatNo": category_id,
      # 전시카테고리(FC...) 있으면 사용, 없으면 표준카테고리 fallback
      "dcatLst": [{"mallCd": "LTON", "lfDcatNo": disp_cat_id or category_id}],
      "slTypCd": "GNRL",
      "pdTypCd": "GNRL_GNRL",
      "spdNm": name,
      # 브랜드번호 — 브랜드 API 검색 후 주입 (없으면 무브랜드)
      "brdNo": product.get("brand_no", ""),
      # 제조사: manufacturer 우선, 없으면 brand
      "mfcrNm": manufacturer,
      # 원산지: 무신사 origin 필드 기반 ISO alpha-2 코드
      "oplcCd": origin_code,
      "tdfDvsCd": "01",
      # 판매 기간
      "slStrtDttm": sl_strt,
      "slEndDttm": sl_end,
      # 출고지/배송비정책/회수지/도서산간추가배송정책 (응답 확인: adtnDvCstPolNo)
      "owhpNo": product.get("owhp_no", ""),
      "dvCstPolNo": product.get("dv_cst_pol_no", ""),
      "adtnDvCstPolNo": product.get("island_dv_cst_pol_no", "") or None,
      "rtrpNo": product.get("rtrp_no", ""),
      # 선물포장/메시지
      "prstPckPsbYn": "N",
      "prstMsgPsbYn": "N",
      "pdItmsInfo": notice,
      "purPsbQtyInfo": {
        "itmByMinPurYn": "N",
        "itmByMaxPurPsbQtyYn": "N",
        "maxPurLmtTypCd": "PERIOD",
      },
      "ageLmtCd": "0",
      "prcCmprEpsrYn": "Y",
      "pdStatCd": "NEW",
      "dpYn": "Y",
      "pdFileLst": pd_file_lst if pd_file_lst else None,
      # 상세설명
      "epnLst": [
        {"pdEpnTypCd": "DSCRP", "cnts": detail_html},
      ],
      "cnclPsbYn": "Y",
      "dmstOvsDvDvsCd": "DMST",
      # 수입구분: 공식수입(직수입) — API 확인된 코드 DRC_IMP
      "impDvsCd": "DRC_IMP",
      "dvProcTypCd": "LO_ENTP",
      "dvPdTypCd": "GNRL",
      "sndBgtNday": 2,
      "dvMnsCd": "DPCL",
      "cmbnDvPsbYn": product.get("cmbn_dv_psb_yn", "Y"),
      "cmbnRtngPsbYn": product.get("cmbn_dv_psb_yn", "Y"),
      "rtngPsbYn": "Y",
      "xchgPsbYn": "Y",
      **({"rtngFee": return_fee} if return_fee else {}),
      **({"xchgFee": exchange_fee} if exchange_fee else {}),
      **({"islandAddDlvFee": jeju_fee} if jeju_fee else {}),
      "stkMgtYn": "Y",
      "sitmYn": "Y" if options else "N",
      "itmLst": itm_lst,
      "rtrvTypCd": "ENTP_RTRV",
      "dvRgsprGrpCd": "GN000",
    }

    # ── SEO: 검색 키워드 (있을 때만) ────────────────────────────
    if keywords:
      spd["spdKeyword"] = keywords

    # ── SEO: 상품 소개문 (있을 때만) ────────────────────────────
    if intro:
      spd["pdIntrdCnts"] = intro

    # ── 판매자 상품코드 (품번 있을 때만) ────────────────────────
    if style_code:
      spd["selPrdNo"] = style_code[:50]

    # ── 기타정보 ─────────────────────────────────────────────────
    # 모델번호: 품번(style_code) 활용
    if style_code:
      spd["mdlNo"] = style_code[:50]
    # 온누리상품권 결제가능여부: 기본 사용안함 (응답 확인: onnuriPyPsbYn)
    spd["onnuriPyPsbYn"] = "N"
    # 임직원상품 여부: 기본 해당없음
    spd["empPrdYn"] = "N"
    # 출시년월(rlsYm): 롯데ON Open API 미지원 필드 — 파트너센터에서 수동 입력 필요
    # 제품/포장 사이즈: pdSzInfo 하나의 객체에 모두 포함 (API 응답 확인)
    spd["pdSzInfo"] = {
      "pdWdthSz": 29,   # 제품 가로 (cm)
      "pdLnthSz": 20,   # 제품 세로 (cm)
      "pdHghtSz": 16,   # 제품 높이 (cm)
      "pckWdthSz": 34,  # 포장 가로 (cm)
      "pckLnthSz": 25,  # 포장 세로 (cm)
      "pckHghtSz": 21,  # 포장 높이 (cm)
    }

    # ── 카테고리 속성정보 (scatAttrLst) ─────────────────────────
    # _scat_attr_lst: [{"optCd": attr_id, "optValCd": attr_val_id}, ...]
    # scatAttrChgYn: 수정 API에서 속성정보 변경 여부 명시 플래그 (필요 시)
    scat_attr_lst = product.get("_scat_attr_lst") or []
    if scat_attr_lst:
      spd["scatAttrLst"] = scat_attr_lst
      spd["scatAttrChgYn"] = "Y"

    # ── 상품홍보문구 — 자동 설정 불가
    # - OpenAPI 페이로드에 포함 시 무시됨 (200 OK 반환하지만 미반영)
    # - soapi updateProduct → 403 (API key 권한 없음, 브라우저 세션 전용)
    # 롯데ON 어드민에서 수동 설정 필요
    return {"spdLst": [spd]}

  # ------------------------------------------------------------------
  # 주문 조회 (롯데홈쇼핑 주문 API)
  # ------------------------------------------------------------------

  async def get_orders(self, days: int = 7) -> list[dict[str, str]]:
    """최근 N일 신규주문 조회.

    SelOption=01: 미발주/신규 상태 필터.
    반환: OrdNo, SubOrdNo, OrdProdCode, OrdStat, OrderName 등 주문 dict 리스트.
    """
    start_date, end_date = self._date_range(days)
    xml_text = await self._call_imall_api(
      "/openapi/searchNewOrdLstOpenApi.lotte",
      {
        "start_date": start_date,
        "end_date": end_date,
        "SelOption": "01",
      },
    )
    return self._parse_xml_list(xml_text, "OrdInfo")

  async def get_cancel_orders(self, days: int = 7) -> list[dict[str, str]]:
    """최근 N일 주문취소 조회.

    반환: OrdNo, MbrNm, ClmCausCd, ClmCausNm, CnclDtime 등 취소 dict 리스트.
    """
    start_date, end_date = self._date_range(days)
    xml_text = await self._call_imall_api(
      "/openapi/searchCnclList.lotte",
      {
        "start_date": start_date,
        "end_date": end_date,
      },
    )
    return self._parse_xml_list(xml_text, "CnclInfo")

  async def get_returns(self, days: int = 7) -> list[dict[str, str]]:
    """최근 N일 반품 조회.

    ord_dtl_stat_cd=20: 반품요청 상태 필터.
    반환: OrdNo, OrdDtlSn, MbrNm, ClmCausCd, GoodsNm 등 반품 dict 리스트.
    """
    start_date, end_date = self._date_range(days)
    xml_text = await self._call_imall_api(
      "/openapi/searchReturnList.lotte",
      {
        "start_date": start_date,
        "end_date": end_date,
        "ord_dtl_stat_cd": "20",
      },
    )
    return self._parse_xml_list(xml_text, "ReturnInfo")

  async def approve_return(self, ord_no: str, ord_dtl_sn: str) -> bool:
    """반품 승인 처리.

    proc_gubun=rfin: 반품완료 처리 코드.
    hdc_cd, inv_no는 빈 문자열로 전달 (롯데홈쇼핑 자체 배송 처리).
    반환: 성공 여부
    """
    xml_text = await self._call_imall_api(
      "/openapi/registDeliver.lotte",
      {
        "ord_no": ord_no,
        "ord_dtl_sn": ord_dtl_sn,
        "proc_gubun": "rfin",
        "hdc_cd": "",
        "inv_no": "",
      },
    )
    # 응답 XML에서 Result 태그 확인 (1: 성공)
    try:
      root = ET.fromstring(xml_text)
      result_el = root.find(".//Result")
      if result_el is not None and result_el.text:
        return result_el.text.strip() == "1"
    except ET.ParseError as e:
      logger.warning(f"[롯데홈쇼핑] approve_return XML 파싱 실패: {e} | 원문: {xml_text[:200]}")
    return False

  # ------------------------------------------------------------------
  # CS 문의 조회 및 답변 (VOC)
  # ------------------------------------------------------------------

  async def get_cs_inquiries(self, days: int = 30) -> list[dict[str, str]]:
    """최근 N일 CS 문의(VOC) 조회 (미처리 건).

    proc_stat_cd=01: 미처리 상태 필터.
    반환: CcnNo, MvotReqSn, OrdNo, GoodsNm, MbrNm, VocNm, AnsCont 등 dict 리스트.
    """
    start_date, end_date = self._date_range(days)
    xml_text = await self._call_imall_api(
      "/openapi/searchCSCounselMemoListOpenApi.lotte",
      {
        "req_start_dtime": start_date,
        "req_end_dtime": end_date,
        "proc_stat_cd": "01",
      },
    )
    return self._parse_xml_list(xml_text, "CsInfo")

  async def reply_cs_inquiry(self, ccn_no: str, mvot_req_sn: str, reply: str) -> bool:
    """CS 문의 답변 등록.

    reply: 답변 내용 (최대 4000자).
    반환: 성공 여부 (응답 XML <Result>1</Result> 확인).
    """
    # 답변 내용 4000자 제한
    trimmed_reply = reply[:4000]
    xml_text = await self._call_imall_api(
      "/openapi/updateCounselMemoOpenApi.lotte",
      {
        "ccn_no": ccn_no,
        "mvot_req_sn": mvot_req_sn,
        "cnsl_proc_cont": trimmed_reply,
      },
    )
    # 응답 XML에서 Result 태그 확인 (1: 성공, 2/3: 실패)
    try:
      root = ET.fromstring(xml_text)
      result_el = root.find(".//Result")
      if result_el is not None and result_el.text:
        return result_el.text.strip() == "1"
    except ET.ParseError as e:
      logger.warning(f"[롯데홈쇼핑] reply_cs_inquiry XML 파싱 실패: {e} | 원문: {xml_text[:200]}")
    return False


class LotteonApiError(Exception):
  """롯데ON API 에러."""
  pass
