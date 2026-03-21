"""스마트스토어(네이버 커머스) API 클라이언트 - 상품 등록/수정.

인증 방식: OAuth2 (bcrypt 서명)
- client_id + timestamp → bcrypt hash → Base64 = client_secret_sign
- POST /external/v1/oauth2/token → access_token 발급
- 이후 Bearer 토큰으로 API 호출
"""

from __future__ import annotations

import base64
import time
from typing import Any, Optional

import bcrypt

from backend.domain.samba.proxy.notice_utils import build_smartstore_notice as _build_ss_notice
import httpx

from backend.utils.logger import logger

# 한국/대한민국 등 국내산 키워드
_DOMESTIC_KEYWORDS = {"한국", "대한민국", "korea", "국내", "국산"}

# 나라 → 네이버 원산지 코드 매핑 (GET /v1/product-origin-areas 기반)
_COUNTRY_ORIGIN_CODE: dict[str, str] = {
  # 아시아 (0200)
  "베트남": "0200014", "중국": "0200037", "일본": "0200036", "인도": "0200033",
  "인도네시아": "0200034", "태국": "0200044", "대만": "0200002", "방글라데시": "0200013",
  "캄보디아": "0200040", "미얀마": "0200011", "필리핀": "0200048", "말레이시아": "0200008",
  "파키스탄": "0200047", "스리랑카": "0200019", "싱가포르": "0200021", "홍콩": "0200049",
  "몽골": "0200010", "네팔": "0200001", "라오스": "0200004", "브루나이": "0200017",
  "우즈베키스탄": "0200028", "카자흐스탄": "0200038", "카타르": "0200039",
  "쿠웨이트": "0200041", "바레인": "0200012", "사우디아라비아": "0200018",
  "아랍에미리트": "0200022", "이스라엘": "0200032", "이란": "0200031",
  # 유럽 (0201)
  "이탈리아": "0201038", "프랑스": "0201046", "독일": "0201005", "스페인": "0201025",
  "영국": "0201035", "포르투갈": "0201044", "루마니아": "0201049", "폴란드": "0201045",
  "체코": "0201040", "헝가리": "0201048", "네덜란드": "0201002", "스위스": "0201024",
  "스웨덴": "0201023", "노르웨이": "0201003", "덴마크": "0201004", "핀란드": "0201047",
  "벨기에": "0201017", "오스트리아": "0201036", "그리스": "0201000",
  "아일랜드공화국": "0201029", "러시아연방": "0201007", "터키": "0201042",
  "불가리아": "0201021", "크로아티아": "0201041", "세르비아": "0201050",
  # 북아메리카 (0204)
  "미국": "0204000", "캐나다": "0204006",
  # 라틴아메리카 (0205)
  "멕시코": "0205007", "브라질": "0205015", "아르헨티나": "0205020",
  "칠레": "0205029", "콜롬비아": "0205031", "페루": "0205036",
  # 오세아니아 (0203)
  "호주": "0203024", "뉴질랜드": "0203003",
  # 아프리카 (0202)
  "이집트": "0202039", "남아프리카공화국": "0202008", "모로코": "0202017",
  "에티오피아": "0202036", "케냐": "0202049",
  # 영문 → 한글 매핑
  "vietnam": "0200014", "china": "0200037", "japan": "0200036", "india": "0200033",
  "indonesia": "0200034", "thailand": "0200044", "taiwan": "0200002",
  "cambodia": "0200040", "bangladesh": "0200013", "myanmar": "0200011",
  "italy": "0201038", "france": "0201046", "germany": "0201005", "spain": "0201025",
  "uk": "0201035", "portugal": "0201044", "usa": "0204000", "us": "0204000",
  "canada": "0204006", "australia": "0203024", "new zealand": "0203003",
}


def _format_phone(phone: str) -> str:
  """전화번호 포맷팅 — 010-95940674 → 010-9594-0674."""
  import re
  digits = re.sub(r"[^0-9]", "", phone)
  if not digits:
    return phone
  # 010-xxxx-xxxx
  if len(digits) == 11 and digits.startswith("01"):
    return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
  # 02-xxxx-xxxx (서울)
  if digits.startswith("02"):
    if len(digits) == 10:
      return f"02-{digits[2:6]}-{digits[6:]}"
    if len(digits) == 9:
      return f"02-{digits[2:5]}-{digits[5:]}"
  # 0xx-xxxx-xxxx (지역번호 3자리)
  if len(digits) == 11:
    return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
  if len(digits) == 10:
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
  # 050x-xxxx-xxxx (안심번호)
  if len(digits) == 12 and digits.startswith("05"):
    return f"{digits[:4]}-{digits[4:8]}-{digits[8:]}"
  return phone


def _build_origin_area(origin: str) -> dict:
  """원산지 값에 따라 originAreaInfo를 동적 생성.

  originAreaCode: "00"=국내산, "01"=원양산(해산물), "02"=수입산, "03"=기타
  """
  origin = (origin or "").strip()
  lower = (origin or "").lower()
  if origin and any(kw in lower for kw in _DOMESTIC_KEYWORDS):
    return {"originAreaCode": "00", "content": origin, "plural": False}

  # 수입산: 나라→네이버 고유코드 매핑
  if origin:
    code = _COUNTRY_ORIGIN_CODE.get(origin) or _COUNTRY_ORIGIN_CODE.get(lower, "")
    if not code:
      # 부분 매칭 시도 (예: "베트남산" → "베트남")
      for country, c in _COUNTRY_ORIGIN_CODE.items():
        if country in origin or country in lower:
          code = c
          origin = country
          break
    if code:
      return {
        "originAreaCode": code,
        "content": origin,
        "importer": "판매자 문의",
        "plural": False,
      }

  # 매핑 안 되는 경우 기타(03)
  return {"originAreaCode": "03", "content": origin or "상세설명에 표기", "plural": False}


def _build_combination_options(options: list[dict], sale_price: int) -> dict:
  """수집 옵션 → 스마트스토어 combinationOption 변환.

  옵션명에서 사이즈/색상을 분리하고, 재고·품절 상태를 반영한다.
  """
  # 옵션명 패턴 분석: "02(235)" → 사이즈, "Black / 270" → 색상+사이즈
  has_slash = any("/" in (o.get("name") or "") for o in options)

  if has_slash:
    # 2단 옵션: 색상 / 사이즈
    option_groups = ["색상", "사이즈"]
  else:
    # 1단 옵션: 사이즈만
    option_groups = ["사이즈"]

  combinations = []
  for idx, opt in enumerate(options):
    name = opt.get("name") or opt.get("size") or f"옵션{idx+1}"
    stock = opt.get("stock", 0) or 0
    sold_out = opt.get("isSoldOut", False)

    if sold_out:
      stock = 0

    # 옵션 가격 차이 (기본가 대비)
    opt_price = int(opt.get("price", 0) or 0)
    price_diff = opt_price - sale_price if opt_price > 0 else 0

    if has_slash and "/" in name:
      parts = [p.strip() for p in name.split("/", 1)]
      option_values = parts
    else:
      option_values = [name]

    combinations.append({
      "id": idx + 1,
      "optionName1": option_values[0],
      **({"optionName2": option_values[1]} if len(option_values) > 1 else {}),
      "stockQuantity": max(stock, 0),
      "price": price_diff,
      "usable": not sold_out,
    })

  return {
    "optionCombinationSortType": "CREATE",
    "optionCombinationGroupNames": {
      "optionGroupName1": option_groups[0],
      **({"optionGroupName2": option_groups[1]} if len(option_groups) > 1 else {}),
    },
    "optionCombinations": combinations,
    "useStockManagement": True,
  }


class SmartStoreClient:
  """네이버 커머스 API 클라이언트."""

  BASE_URL = "https://api.commerce.naver.com/external"

  def __init__(self, client_id: str, client_secret: str) -> None:
    self.client_id = client_id
    self.client_secret = client_secret
    self._access_token: str = ""
    self._token_expires_at: float = 0

  # ------------------------------------------------------------------
  # 인증
  # ------------------------------------------------------------------

  async def _ensure_token(self) -> str:
    """유효한 토큰이 없으면 새로 발급."""
    if self._access_token and time.time() < self._token_expires_at - 60:
      return self._access_token

    timestamp = int(time.time() * 1000)
    password = f"{self.client_id}_{timestamp}"
    hashed = bcrypt.hashpw(
      password.encode("utf-8"),
      self.client_secret.encode("utf-8"),
    )
    client_secret_sign = base64.standard_b64encode(hashed).decode("utf-8")

    async with httpx.AsyncClient(timeout=15) as client:
      resp = await client.post(
        f"{self.BASE_URL}/v1/oauth2/token",
        data={
          "client_id": self.client_id,
          "timestamp": timestamp,
          "client_secret_sign": client_secret_sign,
          "grant_type": "client_credentials",
          "type": "SELF",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
      )
      if resp.status_code != 200:
        err = resp.json() if "json" in resp.headers.get("content-type", "") else {}
        raise SmartStoreApiError(
          f"토큰 발급 실패: {err.get('message', resp.status_code)}"
        )
      data = resp.json()
      self._access_token = data["access_token"]
      self._token_expires_at = time.time() + data.get("expires_in", 3600)
      return self._access_token

  async def _call_api(
    self,
    method: str,
    path: str,
    body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
  ) -> dict[str, Any]:
    """공통 API 호출."""
    token = await self._ensure_token()
    url = f"{self.BASE_URL}{path}"
    headers = {
      "Authorization": f"Bearer {token}",
      "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
      if method == "GET":
        resp = await client.get(url, headers=headers, params=params)
      elif method == "POST":
        resp = await client.post(url, headers=headers, json=body or {})
      elif method == "PUT":
        resp = await client.put(url, headers=headers, json=body or {})
      elif method == "PATCH":
        resp = await client.patch(url, headers=headers, json=body or {})
      elif method == "DELETE":
        resp = await client.delete(url, headers=headers)
      else:
        raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

      text = resp.text
      try:
        data = resp.json()
      except Exception:
        data = {"raw": text}

      logger.info(f"[스마트스토어] {method} {path} → {resp.status_code}")

      if not resp.is_success:
        # 네이버 API는 invalidInputs 배열로 상세 에러 제공
        msg = data.get("message", "") or data.get("reason", "") or text[:200]
        invalid_inputs = data.get("invalidInputs") or []
        if invalid_inputs:
          logger.error(f"[스마트스토어] invalidInputs 원본: {invalid_inputs}")
          details = "; ".join(
            f"{iv.get('name', iv.get('field', '?'))}: {iv.get('message', '')}" for iv in invalid_inputs if isinstance(iv, dict)
          )
          msg = f"{msg} [{details}]"
        raise SmartStoreApiError(f"HTTP {resp.status_code}: {msg}")

      return data

  # ------------------------------------------------------------------
  # 채널(스토어) 정보 조회
  # ------------------------------------------------------------------

  async def get_channel_info(self) -> dict[str, Any]:
    """채널(스토어) 정보를 조회하여 스토어 슬러그 등 반환."""
    result = await self._call_api("GET", "/v1/seller/channels")
    logger.info(f"[스마트스토어] 채널 조회 raw: {result}")

    # 다양한 응답 구조 대응
    channels: list[Any] = []
    if isinstance(result, list):
      channels = result
    elif isinstance(result, dict):
      for key in ("contents", "channels", "data", "result"):
        val = result.get(key)
        if isinstance(val, list) and val:
          channels = val
          break
      # 단일 객체 응답 (channelNo가 최상위에 있는 경우)
      if not channels and result.get("channelNo"):
        channels = [result]

    if not channels:
      logger.warning("[스마트스토어] 채널 목록이 비어있음")
      return {}

    ch = channels[0]
    # channel이 nested일 수 있음
    if isinstance(ch.get("channel"), dict):
      ch = ch["channel"]

    # URL 필드 다양한 키 시도
    url = ch.get("url") or ch.get("channelUrl") or ch.get("storeUrl") or ""
    slug = url.rstrip("/").split("/")[-1] if url else ""

    logger.info(f"[스마트스토어] 채널 파싱 결과 — url={url}, slug={slug}")

    return {
      "channelNo": ch.get("channelNo", ""),
      "channelName": ch.get("name", ch.get("channelName", "")),
      "storeSlug": slug,
      "url": url,
    }

  async def get_store_slug_fallback(self) -> str:
    """채널 API 실패 시 — 등록된 상품에서 스토어 슬러그 추출."""
    try:
      result = await self._call_api("POST", "/v1/products/search", body={
        "page": 1, "size": 1,
      })
      logger.info(f"[스마트스토어] 슬러그 fallback 상품검색 raw: {result}")

      # 응답에서 상품 목록 추출
      contents = []
      if isinstance(result, dict):
        contents = result.get("contents", result.get("data", []))
      if isinstance(result, list):
        contents = result

      if not contents:
        return ""

      product = contents[0]
      # 상품의 smartStoreUrl 또는 channelProducts에서 URL 추출
      store_url = product.get("smartStoreUrl", "")
      if not store_url:
        channel_products = product.get("channelProducts", [])
        for cp in channel_products:
          cp_url = cp.get("url") or cp.get("channelProductUrl") or ""
          if "smartstore.naver.com" in cp_url:
            store_url = cp_url
            break

      if store_url and "smartstore.naver.com" in store_url:
        # https://smartstore.naver.com/슬러그/products/... → 슬러그 추출
        parts = store_url.split("smartstore.naver.com/")
        if len(parts) > 1:
          slug = parts[1].split("/")[0]
          logger.info(f"[스마트스토어] fallback 슬러그 추출: {slug}")
          return slug

      return ""
    except Exception as e:
      logger.warning(f"[스마트스토어] 슬러그 fallback 실패: {e}")
      return ""

  # ------------------------------------------------------------------
  # 카테고리 조회
  # ------------------------------------------------------------------

  async def get_categories(self, last_only: bool = True) -> list[dict[str, Any]]:
    """네이버 커머스 카테고리 전체 조회.

    GET /v1/categories?last={true|false}
    응답: [{wholeCategoryName, id, name, last}, ...]
    """
    params = {"last": str(last_only).lower()}
    return await self._call_api("GET", "/v1/categories", params=params)

  # ------------------------------------------------------------------
  # 브랜드 검색
  # ------------------------------------------------------------------

  async def search_brand(self, brand_name: str) -> Optional[int]:
    """브랜드명으로 네이버 브랜드 ID 검색. 없으면 None."""
    if not brand_name or brand_name in ("상세설명 참조", "상세 이미지 참조"):
      return None
    try:
      result = await self._call_api("GET", "/v1/product-brands", params={"name": brand_name})
      # 네이버 API 응답: {"contents": [...]} 또는 직접 리스트
      brands = result
      if isinstance(result, dict):
        brands = result.get("contents") or result.get("brands") or result.get("data") or []
      if not isinstance(brands, list):
        brands = []
      logger.info(f"[스마트스토어] 브랜드 검색: {brand_name} → {len(brands)}건")
      for b in brands:
        if b.get("name") == brand_name:
          return b.get("id")
      # 정확 매치 없으면 첫 번째 결과
      if brands:
        return brands[0].get("id")
    except Exception as e:
      logger.warning(f"[스마트스토어] 브랜드 검색 실패 ({brand_name}): {e}")
    return None

  async def search_manufacturer(self, mfr_name: str) -> Optional[int]:
    """제조사명으로 네이버 제조사 ID 검색. 없으면 None."""
    if not mfr_name:
      return None
    try:
      result = await self._call_api("GET", "/v1/product-manufacturers", params={"name": mfr_name})
      if isinstance(result, list):
        for m in result:
          if m.get("name") == mfr_name:
            return m.get("id")
        if result:
          return result[0].get("id")
    except Exception as e:
      logger.warning(f"[스마트스토어] 제조사 검색 실패 ({mfr_name}): {e}")
    return None

  async def get_category_attributes(self, category_id: str) -> list[dict[str, Any]]:
    """카테고리별 상품속성 값 목록 조회."""
    if not category_id:
      return []
    try:
      result = await self._call_api(
        "GET", "/v1/product-attributes/attribute-values",
        params={"categoryId": category_id},
      )
      # 네이버 API 응답: 리스트 또는 {"contents": [...]}
      if isinstance(result, list):
        return result
      if isinstance(result, dict):
        return result.get("contents") or result.get("data") or result.get("attributeValues") or []
      return []
    except Exception as e:
      logger.warning(f"[스마트스토어] 카테고리 속성 조회 실패 ({category_id}): {e}")
      return []

  # ------------------------------------------------------------------
  # 상품 등록
  # ------------------------------------------------------------------

  async def upload_image_from_url(self, image_url: str) -> str:
    """외부 이미지 URL을 네이버 커머스에 업로드하고 네이버 URL을 반환."""
    token = await self._ensure_token()
    # 이미지 다운로드
    # 이미지 원본 도메인을 Referer로 사용 (CDN 핫링크 방지 우회)
    from urllib.parse import urlparse
    parsed = urlparse(image_url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    # 무신사 CDN은 musinsa.com Referer가 필요
    if "msscdn.net" in (parsed.netloc or ""):
      referer = "https://www.musinsa.com/"

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
      img_resp = await client.get(image_url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": referer,
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
      })
      if not img_resp.is_success:
        raise SmartStoreApiError(f"이미지 다운로드 실패: {img_resp.status_code}")
      img_bytes = img_resp.content
      content_type = img_resp.headers.get("content-type", "image/jpeg")
      # CDN 경고 이미지 감지 (너무 작으면 핫링크 차단 이미지일 가능성)
      if len(img_bytes) < 1000:
        raise SmartStoreApiError(f"이미지가 비정상적으로 작음({len(img_bytes)}B) — CDN 차단 가능성")

    # EXIF 메타데이터 제거
    from backend.domain.samba.image.exif import strip_exif
    img_bytes = strip_exif(img_bytes)

    # 네이버 이미지 업로드 API
    ext = "jpg"
    if "png" in content_type:
      ext = "png"
    elif "webp" in content_type:
      ext = "webp"

    async with httpx.AsyncClient(timeout=30) as client:
      resp = await client.post(
        f"{self.BASE_URL}/v1/product-images/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"imageFiles": (f"image.{ext}", img_bytes, content_type)},
      )
      if not resp.is_success:
        raise SmartStoreApiError(f"이미지 업로드 실패: {resp.status_code} {resp.text[:200]}")
      data = resp.json()
      images = data.get("images", [])
      if not images:
        raise SmartStoreApiError("이미지 업로드 응답에 URL 없음")
      return images[0].get("url", "")

  async def register_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
    """상품 등록.

    product_data 예시:
    {
      "originProduct": {
        "statusType": "SALE",
        "saleType": "NEW",
        "leafCategoryId": "50000803",
        "name": "상품명",
        "detailContent": "<p>상세설명 HTML</p>",
        "images": {
          "representativeImage": {"url": "https://..."},
          "optionalImages": [{"url": "https://..."}]
        },
        "salePrice": 29900,
        "stockQuantity": 999,
        "deliveryInfo": {
          "deliveryType": "DELIVERY",
          "deliveryAttributeType": "NORMAL",
          "deliveryFee": {"deliveryFeeType": "FREE"}
        },
        "detailAttribute": {
          "afterServiceInfo": {"afterServiceTelephoneNumber": "02-0000-0000", "afterServiceGuideContent": "A/S 안내"},
          "originAreaInfo": {"originAreaCode": "03", "content": "상세설명에 표기"}
        }
      },
      "smartstoreChannelProduct": {
        "channelProductName": "스마트스토어 노출 상품명",
        "storeKeepExclusiveProduct": false
      }
    }
    """
    result = await self._call_api("POST", "/v2/products", body=product_data)
    return {"success": True, "data": result}

  async def update_product(
    self, product_no: str, product_data: dict[str, Any]
  ) -> dict[str, Any]:
    """상품 수정."""
    result = await self._call_api("PATCH", f"/v2/products/origin-products/{product_no}", body=product_data)
    return {"success": True, "data": result}

  async def delete_product(self, product_no: str) -> dict[str, Any]:
    """상품 삭제 (리스트에서 완전 제거)."""
    result = await self._call_api("DELETE", f"/v2/products/origin-products/{product_no}")
    return {"success": True, "data": result}

  async def get_product(self, product_no: str) -> dict[str, Any]:
    """상품 조회."""
    return await self._call_api("GET", f"/v2/products/origin-products/{product_no}")

  # ------------------------------------------------------------------
  # 주문 조회
  # ------------------------------------------------------------------

  async def get_orders(
    self,
    days: int = 7,
    order_status: str = "",
  ) -> list[dict[str, Any]]:
    """최근 N일간 주문 조회.

    Commerce API: GET /v1/pay-order/seller/product-orders/last-changed-statuses
    """
    from datetime import datetime, timedelta, timezone

    # KST 기준으로 시작 시간 계산 (스마트스토어 API 최대 90일 제한)
    kst = timezone(timedelta(hours=9))
    effective_days = min(days, 89)
    since = datetime.now(kst) - timedelta(days=effective_days)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%S.000+09:00")

    params: dict[str, Any] = {
      "lastChangedFrom": since_str,
    }
    if order_status:
      params["lastChangedType"] = order_status

    # 1단계: 변경된 주문 ID 목록 조회 (여러 구간으로 분할하여 누락 방지)
    logger.info(f"[스마트스토어] 주문 조회 시작 lastChangedFrom={since_str}")

    all_statuses: list[dict[str, Any]] = []
    seen_po_ids: set[str] = set()

    # 요청 기간 + 최근 1일 병행 조회 (API 시크릿 재발급 등으로 과거 데이터 조회 불가 대비)
    query_dates = [since_str]
    recent = datetime.now(kst) - timedelta(days=1)
    recent_str = recent.strftime("%Y-%m-%dT%H:%M:%S.000+09:00")
    if recent_str != since_str:
      query_dates.append(recent_str)

    for qdate in query_dates:
      qparams = dict(params)
      qparams["lastChangedFrom"] = qdate
      result = await self._call_api(
        "GET",
        "/v1/pay-order/seller/product-orders/last-changed-statuses",
        params=qparams,
      )
      data = result.get("data", result) if isinstance(result, dict) else {}
      statuses = data.get("lastChangeStatuses", []) if isinstance(data, dict) else []
      for s in statuses:
        pid = s.get("productOrderId", "")
        if pid and pid not in seen_po_ids:
          seen_po_ids.add(pid)
          all_statuses.append(s)

    logger.info(f"[스마트스토어] 변경된 주문 수: {len(all_statuses)}")

    if not all_statuses:
      return []

    statuses = all_statuses

    # 2단계: 주문 상세 조회
    po_ids = [s.get("productOrderId") for s in statuses if s.get("productOrderId")]
    if not po_ids:
      return []

    logger.info(f"[스마트스토어] 상세 조회 대상: {len(po_ids)}건")
    details_result = await self._call_api(
      "POST",
      "/v1/pay-order/seller/product-orders/query",
      body={"productOrderIds": po_ids[:300]},
    )

    details_data = details_result.get("data", details_result) if isinstance(details_result, dict) else details_result
    # data가 리스트이면 그대로 사용, 딕셔너리면 productOrders 키에서 추출
    if isinstance(details_data, list):
      orders_data = details_data
    elif isinstance(details_data, dict):
      orders_data = details_data.get("productOrders", [])
    else:
      orders_data = []
    logger.info(f"[스마트스토어] 주문 상세 결과: {len(orders_data)}건")
    return orders_data

  async def confirm_product_orders(
    self, product_order_ids: list[str]
  ) -> dict[str, Any]:
    """발주확인 (placeOrderStatus: NOT_YET → OK).

    Commerce API: POST /v1/pay-order/seller/product-orders/confirm
    """
    result = await self._call_api(
      "POST",
      "/v1/pay-order/seller/product-orders/confirm",
      body={"productOrderIds": product_order_ids},
    )
    logger.info(f"[스마트스토어] 발주확인 {len(product_order_ids)}건 요청")
    return result

  async def approve_cancel(self, product_order_id: str) -> dict[str, Any]:
    """취소요청 승인.

    Commerce API: POST /v1/pay-order/seller/product-orders/{id}/claim/cancel/approve
    """
    result = await self._call_api(
      "POST",
      f"/v1/pay-order/seller/product-orders/{product_order_id}/claim/cancel/approve",
    )
    logger.info(f"[스마트스토어] 취소승인 완료: {product_order_id}")
    return result

  # ------------------------------------------------------------------
  # 상품 데이터 변환 (수집 상품 → 스마트스토어 형식)
  # ------------------------------------------------------------------

  @staticmethod
  def transform_product(
    product: dict[str, Any],
    category_id: str = "",
    delivery_fee_type: str = "FREE",
  ) -> dict[str, Any]:
    """SambaCollectedProduct → 스마트스토어 상품 등록 데이터 변환."""
    images_raw = product.get("images") or []

    representative = {"url": images_raw[0]} if images_raw else {}
    # 수집 시 이미 상세이미지로 보충됨 — images[1:5] 그대로 사용
    optional = [{"url": u} for u in images_raw[1:5]]

    desired_price = int(product.get("sale_price", 0))
    if desired_price <= 0:
      desired_price = int(product.get("original_price", 0)) or 10000

    # 즉시할인: 원하는 판매가를 역산하여 판매가 설정
    # 예) 원하는 가격 80,000 + 할인율 20% → 판매가 100,000 + 즉시할인 20% = 할인가 80,000
    discount_rate = product.get("_discount_rate", 0)
    immediate_discount = None
    if discount_rate and 0 < discount_rate < 100:
      sale_price = int(desired_price / (1 - discount_rate / 100))
      # 10원 단위 올림
      sale_price = ((sale_price + 9) // 10) * 10
      immediate_discount = True
    else:
      sale_price = ((desired_price + 9) // 10) * 10

    brand = product.get("brand", "") or "상세설명 참조"
    # 제조사: manufacturer → brand → "상세설명 참조" 순으로 폴백
    raw_mfr = product.get("manufacturer", "")
    mfr = raw_mfr if (raw_mfr and raw_mfr != "상세설명 참조" and raw_mfr != "상세 이미지 참조") else ""
    if not mfr:
      raw_brand = product.get("brand", "")
      mfr = raw_brand if (raw_brand and raw_brand != "상세설명 참조" and raw_brand != "상세 이미지 참조") else "상세설명 참조"

    # 옵션에서 사이즈 정보 추출
    options = product.get("options") or []
    sizes = [o.get("size", "") or o.get("name", "") for o in options if o.get("size") or o.get("name")]
    size_text = ", ".join(sorted(set(s for s in sizes if s)))[:200] or "상세설명 참조"

    # 색상: DB 필드 우선, 상품명에서 추출
    color_part = ""
    if " - " in product.get("name", ""):
      color_part = product["name"].split(" - ", 1)[1].split("/")[0].strip()
    db_color = product.get("color", "")
    color_text = db_color or (color_part[:200] if color_part else "상세 이미지 참조")

    # 재고수량: 설정값 > 정책 제한 > 실재고 순 우선
    setting_stock = product.get("_stock_quantity", 0)
    max_stock = product.get("_max_stock", 0)
    real_stock = sum(
      (o.get("stock") or 0) for o in options if not o.get("isSoldOut")
    ) if options else 999
    if setting_stock and setting_stock > 0:
      stock_qty = setting_stock
    elif max_stock and max_stock > 0:
      stock_qty = min(max_stock, real_stock) if real_stock > 0 else max_stock
    else:
      stock_qty = real_stock if real_stock > 0 else 999

    # 모델명/품번 — 공통 컬럼 우선, kream_data 폴백
    style_code = product.get("style_code", "") or product.get("styleCode", "")
    if not style_code:
      kream = product.get("kream_data") or {}
      if isinstance(kream, dict):
        style_code = kream.get("styleCode", "")

    # 성별 — 수집 데이터에 명시된 경우만 사용, 없으면 남녀공용
    sex_raw = product.get("sex", "")
    sex_list: list[str] = []
    if sex_raw:
      sex_list = [sex_raw] if isinstance(sex_raw, str) else list(sex_raw)

    # 시즌 — 공통 컬럼
    season = product.get("season", "") or ""

    # 상품 속성 구성 (카테고리별 API 속성 기반)
    product_attributes: list[dict[str, Any]] = []
    cat_attrs = product.get("_category_attributes") or []

    # 성별 속성 — API 속성에서 성별 seq 찾기, 기본값 남녀공용
    _GENDER_KEYWORDS = {"남성용", "여성용", "남녀공용", "공용", "유니섹스"}
    gender_seq = None
    gender_values: dict[str, int] = {}
    for a in cat_attrs:
      val = a.get("minAttributeValue", "")
      if val in _GENDER_KEYWORDS:
        gender_seq = a["attributeSeq"]
        gender_values[val] = a.get("attributeValueSeq", 0)

    if gender_seq:
      # 수집 데이터에서 성별 판단
      if sex_list:
        sex_val = sex_list[0] if isinstance(sex_list, list) else str(sex_list)
        if "공용" in sex_val or "남녀" in sex_val or "유니" in sex_val:
          target = "남녀공용"
        elif "남" in sex_val:
          target = "남성용"
        elif "여" in sex_val:
          target = "여성용"
        else:
          target = "남녀공용"
      else:
        target = "남녀공용"
      if target in gender_values:
        product_attributes.append({
          "attributeSeq": gender_seq,
          "attributeValueSeq": gender_values[target],
        })

    # 사용계절 속성 — 기본값 전체(봄/여름/가을/겨울)
    _SEASON_KEYWORDS = {"봄", "여름", "가을", "겨울"}
    season_seq = None
    season_values: dict[str, int] = {}
    for a in cat_attrs:
      val = a.get("minAttributeValue", "")
      if val in _SEASON_KEYWORDS:
        season_seq = a["attributeSeq"]
        season_values[val] = a.get("attributeValueSeq", 0)
    if season_seq:
      for s in ["봄", "여름", "가을", "겨울"]:
        if s in season_values:
          product_attributes.append({
            "attributeSeq": season_seq,
            "attributeValueSeq": season_values[s],
          })

    # 종류 속성 — 카테고리(category1~4)로 추정하여 매칭
    type_seq = None
    type_values: dict[str, int] = {}
    _TYPE_SKIP = _GENDER_KEYWORDS | _SEASON_KEYWORDS | {"기타", "해당없음"}
    for a in cat_attrs:
      val = a.get("minAttributeValue", "")
      seq = a.get("attributeSeq", 0)
      if val and val not in _TYPE_SKIP and seq != gender_seq and seq != season_seq:
        if type_seq is None:
          type_seq = seq
        if seq == type_seq:
          type_values[val] = a.get("attributeValueSeq", 0)

    if type_seq and type_values:
      cat_keywords = [
        product.get("category1", ""), product.get("category2", ""),
        product.get("category3", ""), product.get("category4", ""),
      ]
      cat_text = " ".join(c for c in cat_keywords if c)
      matched_type = None
      for type_name in type_values:
        if type_name in cat_text:
          matched_type = type_name
          break
      if not matched_type:
        matched_type = next(iter(type_values))
      if matched_type:
        product_attributes.append({
          "attributeSeq": type_seq,
          "attributeValueSeq": type_values[matched_type],
        })

    data: dict[str, Any] = {
      "originProduct": {
        "statusType": "SALE",
        "saleType": "NEW",
        "leafCategoryId": category_id or "50000803",
        "name": product.get("name", ""),
        # 품번 → sellerCodeInfo.sellerManagementCode
        **({"sellerCodeInfo": {"sellerManagementCode": style_code}} if style_code else {}),
        "detailContent": product.get("detail_html", "") or f"<p>{product.get('name', '')}</p>",
        "images": {
          "representativeImage": representative,
          "optionalImages": optional,
        },
        "salePrice": sale_price,
        "stockQuantity": stock_qty,
        "deliveryInfo": {
          "deliveryType": "DELIVERY",
          "deliveryAttributeType": "NORMAL",
          "deliveryCompany": "CJGLS",
          "deliveryFee": {
            "deliveryFeeType": delivery_fee_type,
            "baseFee": 0,
            "deliveryFeeByArea": {
              "deliveryAreaType": "AREA_2",
              "area2extraFee": product.get("_jeju_fee", 3000),
            },
          },
          "claimDeliveryInfo": {
            "returnDeliveryFee": product.get("_return_fee", 3000),
            "exchangeDeliveryFee": product.get("_exchange_fee", 6000),
            **({"freeReturnInsuranceYn": True} if product.get("_return_safeguard") else {}),
          },
        },
        "detailAttribute": {
          "afterServiceInfo": {
            "afterServiceTelephoneNumber": _format_phone(product.get("_as_phone", "") or "상세페이지 참조"),
            "afterServiceGuideContent": product.get("_as_message", "") or "상세페이지 참조",
          },
          "originAreaInfo": _build_origin_area(product.get("origin", "")),
          "minorPurchasable": True,
          "productInfoProvidedNotice": _build_ss_notice(
            product, color_text=color_text,
            size_text=f"발길이(mm): {size_text}" if sizes else "FREE (상세 이미지 참조)",
            mfr=mfr, brand=brand,
          ),
        },
        **({"optionInfo": _build_combination_options(options, sale_price)} if options else {}),
      },
      "smartstoreChannelProduct": {
        "channelProductName": product.get("name", ""),
        "storeKeepExclusiveProduct": False,
        "naverShoppingRegistration": product.get("_naver_shopping", True),
        "channelProductDisplayStatusType": "ON",
      },
    }

    # 즉시할인 적용
    if immediate_discount:
      data["originProduct"]["customerBenefit"] = {
        "immediateDiscountPolicy": {
          "discountMethod": {
            "value": discount_rate,
            "unitType": "PERCENT",
          },
        },
      }

    # 모델명/품번 입력 — style_code 없으면 상품명에서 추출 시도
    if not style_code:
      # 상품명에서 영숫자 품번 패턴 추출 (예: DUF24G03R2)
      import re
      code_match = re.search(r'[A-Z]{2,}[\dA-Z]{4,}', product.get("name", ""))
      if code_match:
        style_code = code_match.group()
    if style_code:
      data["originProduct"]["detailAttribute"]["modelName"] = style_code
      data["originProduct"]["detailAttribute"]["productNumber"] = style_code

    # 브랜드/제조사 — naverShoppingSearchInfo에 설정 (스마트스토어 상품주요정보)
    naver_search_info: dict[str, Any] = {}
    brand_id = product.get("_brand_id")
    mfr_id = product.get("_manufacturer_id")
    if brand_id:
      naver_search_info["brandId"] = brand_id
      naver_search_info["brandName"] = brand
    elif brand and brand != "상세설명 참조":
      naver_search_info["brandName"] = brand
    if mfr_id:
      naver_search_info["manufacturerId"] = mfr_id
      naver_search_info["manufacturerName"] = mfr
    elif mfr:
      naver_search_info["manufacturerName"] = mfr
    # 모델명도 naverShoppingSearchInfo에 추가 (상품 주요정보에 표시)
    if style_code:
      naver_search_info["modelName"] = style_code
    if naver_search_info:
      data["originProduct"]["detailAttribute"]["naverShoppingSearchInfo"] = naver_search_info

    # 상품속성 (성별, 시즌 등)
    if product_attributes:
      data["originProduct"]["detailAttribute"]["productAttributes"] = product_attributes

    # 복수구매할인
    if product.get("_multi_purchase"):
      multi_qty = product.get("_multi_purchase_qty", 2)
      multi_rate = product.get("_multi_purchase_rate", 1)
      benefit = data["originProduct"].get("customerBenefit", {})
      benefit["multiPurchaseDiscountPolicy"] = {
        "discountMethod": {
          "value": multi_rate,
          "unitType": "PERCENT",
        },
        "orderValue": multi_qty,
        "orderValueUnitType": "COUNT",
      }
      data["originProduct"]["customerBenefit"] = benefit

    # 포인트/리뷰 정책 (customerBenefit 하위)
    if product.get("_purchase_point"):
      benefit = data["originProduct"].get("customerBenefit", {})
      rate = product.get("_purchase_point_rate", 1)
      benefit["purchasePointPolicy"] = {
        "pointPayYn": True,
        "value": rate,
        "unitType": "PERCENT",
      }
      data["originProduct"]["customerBenefit"] = benefit

    if product.get("_review_point"):
      benefit = data["originProduct"].get("customerBenefit", {})
      review_policy: dict[str, Any] = {"reviewPointPayYn": True}
      text_pt = product.get("_review_text_point", 0)
      photo_pt = product.get("_review_photo_point", 0)
      month_text_pt = product.get("_review_month_text_point", 0)
      month_photo_pt = product.get("_review_month_photo_point", 0)
      if text_pt:
        review_policy["textReviewPoint"] = text_pt
      if photo_pt:
        review_policy["photoVideoReviewPoint"] = photo_pt
      if month_text_pt:
        review_policy["afterUseTextReviewPoint"] = month_text_pt
      if month_photo_pt:
        review_policy["afterUsePhotoVideoReviewPoint"] = month_photo_pt
      benefit["reviewPointPolicy"] = review_policy
      data["originProduct"]["customerBenefit"] = benefit

    # 알림받기 동의고객 포인트: Commerce API v2 미지원 → 셀러센터에서 직접 설정

    # 태그 → originProduct.detailAttribute.seoInfo.sellerTags (네이버 커머스 API v2.67)
    tags = product.get("tags") or []
    # 시스템 내부 마커(__ai_tagged__ 등) 제외 + 브랜드/상품명 포함 태그 제외
    brand_lower = brand.lower() if brand else ""
    name_lower = (product.get("name", "") or "").lower()
    seller_tags = []
    for t in tags:
      if t.startswith("__"):
        continue
      tl = t.lower()
      # 브랜드명이 태그에 포함되면 제외 (네이버 금지)
      if brand_lower and brand_lower in tl:
        continue
      # 상품명에 이미 포함된 단어면 제외
      if tl in name_lower:
        continue
      seller_tags.append(t)
      if len(seller_tags) >= 10:
        break
    if seller_tags:
      data["originProduct"]["detailAttribute"]["seoInfo"] = {
        "sellerTags": [{"text": t} for t in seller_tags],
      }
      logger.info(f"[스마트스토어] sellerTags {len(seller_tags)}개 전송: {seller_tags[:3]}...")

    review_photo = product.get("_review_photo_url")
    if review_photo:
      benefit = data["originProduct"].get("customerBenefit", {})
      if "reviewPointPolicy" not in benefit:
        benefit["reviewPointPolicy"] = {}
      benefit["reviewPointPolicy"]["reviewPhotoBenefitImageUrl"] = review_photo
      data["originProduct"]["customerBenefit"] = benefit

    return data


class SmartStoreApiError(Exception):
  """스마트스토어 API 에러."""
  pass
