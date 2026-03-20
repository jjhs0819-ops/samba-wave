"""마켓 디스패처 - 마켓 타입에 따라 실제 API 호출을 라우팅.

각 마켓의 설정은 samba_settings 테이블에 store_{market_type} 키로 저장되어 있다.
수집 상품 데이터를 각 마켓 형식으로 변환하여 실제 API를 호출한다.
"""

from __future__ import annotations

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.forbidden.model import SambaSettings
from backend.domain.samba.forbidden.repository import SambaSettingsRepository
from backend.utils.logger import logger


async def _get_setting(session: AsyncSession, key: str) -> Any:
  """samba_settings 테이블에서 설정값 조회."""
  repo = SambaSettingsRepository(session)
  row = await repo.find_by_async(key=key)
  if row:
    return row.value
  return None


# 마켓별 필수필드 정의 — 전송 전 사전 검증용
MARKET_REQUIRED_FIELDS: dict[str, list[str]] = {
  "smartstore": ["name", "sale_price"],
  "coupang": ["name", "sale_price"],
  "11st": ["name", "sale_price"],
  "lotteon": ["name", "sale_price"],
  "ssg": ["name", "sale_price"],
  "lottehome": ["name", "sale_price"],
  "gsshop": ["name", "sale_price"],
  "kream": ["name", "sale_price"],
  "ebay": ["name", "sale_price"],
  "lazada": ["name", "sale_price"],
  "qoo10": ["name", "sale_price"],
  "shopee": ["name", "sale_price"],
  "shopify": ["name", "sale_price"],
  "zoom": ["name", "sale_price"],
}


def validate_transform(market_type: str, product: dict) -> list[str]:
  """전송 전 필수필드 누락 검사 → 누락 필드명 리스트 반환."""
  required = MARKET_REQUIRED_FIELDS.get(market_type, [])
  missing = []
  for field in required:
    val = product.get(field)
    if val is None or val == "" or val == 0:
      missing.append(field)
  return missing


async def dispatch_to_market(
  session: AsyncSession,
  market_type: str,
  product: dict[str, Any],
  category_id: str = "",
  account: Any = None,
) -> dict[str, Any]:
  """마켓 타입에 따라 실제 상품 등록 API를 호출.

  Args:
    session: DB 세션
    market_type: 마켓 구분
    product: SambaCollectedProduct 딕셔너리
    category_id: 대상 마켓 카테고리 코드
    account: SambaMarketAccount 객체 (계정별 인증 정보)

  Returns:
    {"success": bool, "message": str, "data": Any}
  """
  missing = validate_transform(market_type, product)
  if missing:
    return {
      "success": False,
      "error_type": "schema_changed",
      "message": f"필수필드 누락: {', '.join(missing)}",
    }

  try:
    handler = MARKET_HANDLERS.get(market_type)
    if not handler:
      return {
        "success": False,
        "error_type": "unsupported",
        "message": f"지원하지 않는 마켓: {market_type}",
      }
    return await handler(session, product, category_id, account=account)
  except Exception as exc:
    exc_str = str(exc).lower()
    # 에러 분류: 인증 실패 vs API 스펙 변경 vs 네트워크
    if "401" in exc_str or "403" in exc_str or "unauthorized" in exc_str or "인증" in exc_str:
      error_type = "auth_failed"
    elif "400" in exc_str or "422" in exc_str or "필수" in exc_str or "required" in exc_str:
      error_type = "schema_changed"
    elif "timeout" in exc_str or "connect" in exc_str or "network" in exc_str:
      error_type = "network"
    else:
      error_type = "unknown"
    logger.error(f"[디스패처] {market_type} 상품 등록 실패 ({error_type}): {exc}")
    return {
      "success": False,
      "error_type": error_type,
      "message": f"{market_type} 등록 실패: {str(exc)}",
    }


# ═══════════════════════════════════════════════
# 마켓별 핸들러
# ═══════════════════════════════════════════════


async def _handle_smartstore(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None,
) -> dict[str, Any]:
  """스마트스토어 상품 등록."""
  from backend.domain.samba.proxy.smartstore import SmartStoreClient

  # 계정 객체에서 인증 정보 우선 사용
  client_id = ""
  client_secret = ""
  if account:
    extras = account.additional_fields or {}
    client_id = extras.get("clientId", "") or account.api_key or ""
    client_secret = extras.get("clientSecret", "") or account.api_secret or ""

  # fallback: Settings 테이블 (계정 객체가 없을 때만)
  if not client_id or not client_secret:
    if account:
      # 계정은 있지만 인증정보가 없는 경우 — 해당 계정의 seller_id로 로그
      seller = getattr(account, "seller_id", "?")
      logger.warning(f"[스마트스토어] 계정 {seller}에 인증정보 없음 — 설정 탭에서 수정 후 저장해주세요")
    creds = await _get_setting(session, "store_smartstore")
    if creds and isinstance(creds, dict):
      client_id = client_id or creds.get("clientId", "")
      client_secret = client_secret or creds.get("clientSecret", "")

  if not client_id or not client_secret:
    return {"success": False, "message": "스마트스토어 Client ID/Secret이 없습니다. 설정에서 해당 계정을 수정 후 저장해주세요."}

  # 카테고리 코드가 숫자가 아니면 경고 (경로 문자열은 API에서 사용 불가)
  if category_id and not category_id.isdigit():
    logger.warning(f"[스마트스토어] 카테고리 '{category_id}'가 숫자 코드가 아님 — 기본 카테고리 사용")
    category_id = ""

  if not category_id:
    return {"success": False, "message": "스마트스토어 카테고리 코드가 없습니다. 카테고리 매핑을 설정해주세요."}

  client = SmartStoreClient(client_id, client_secret)

  # 대표이미지 URL을 네이버에 업로드 후 변환
  images_raw = product.get("images") or []
  naver_images = []
  for img_url in images_raw[:5]:
    try:
      naver_url = await client.upload_image_from_url(img_url)
      if naver_url:
        naver_images.append(naver_url)
    except Exception as e:
      logger.warning(f"[스마트스토어] 대표이미지 업로드 실패: {e}")

  # 상세페이지 HTML 내 이미지도 네이버에 업로드하여 URL 치환
  # (소싱처 CDN URL 그대로 사용하면 핫링크 차단됨)
  detail_html = product.get("detail_html", "")
  if detail_html:
    import re
    img_pattern = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)
    all_src_urls = img_pattern.findall(detail_html)
    # 외부 CDN URL만 업로드 (네이버 URL이나 S3 URL은 제외)
    url_map: dict[str, str] = {}
    for src_url in all_src_urls:
      if src_url in url_map:
        continue
      # 이미 네이버 CDN이면 스킵
      if "naver.net" in src_url or "pstatic.net" in src_url:
        continue
      try:
        naver_url = await client.upload_image_from_url(src_url)
        if naver_url:
          url_map[src_url] = naver_url
      except Exception as e:
        logger.warning(f"[스마트스토어] 상세이미지 업로드 실패 ({src_url[:60]}): {e}")
    # URL 치환
    for old_url, new_url in url_map.items():
      detail_html = detail_html.replace(old_url, new_url)
    logger.info(f"[스마트스토어] 상세이미지 {len(url_map)}개 네이버 업로드 완료")

  # 업로드된 이미지로 상품 데이터 변환
  product_copy = dict(product)
  if naver_images:
    product_copy["images"] = naver_images
  if detail_html:
    product_copy["detail_html"] = detail_html

  data = SmartStoreClient.transform_product(product_copy, category_id)
  result = await client.register_product(data)
  return {"success": True, "message": "스마트스토어 등록 성공", "data": result}


async def _handle_coupang(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None,
) -> dict[str, Any]:
  """쿠팡 상품 등록."""
  from backend.domain.samba.proxy.coupang import CoupangClient

  access_key = ""
  secret_key = ""
  vendor_id = ""
  if account:
    extras = account.additional_fields or {}
    access_key = extras.get("accessKey", "") or account.api_key or ""
    secret_key = extras.get("secretKey", "") or account.api_secret or ""
    vendor_id = extras.get("vendorId", "") or account.seller_id or ""

  if not access_key or not secret_key:
    creds = await _get_setting(session, "store_coupang")
    if creds and isinstance(creds, dict):
      access_key = access_key or creds.get("accessKey", "")
      secret_key = secret_key or creds.get("secretKey", "")
      vendor_id = vendor_id or creds.get("vendorId", "")

  if not access_key or not secret_key:
    return {"success": False, "message": "쿠팡 Access Key/Secret Key가 없습니다."}

  client = CoupangClient(access_key, secret_key, vendor_id)

  # 카테고리 코드가 숫자가 아니면 쿠팡 API로 동적 조회
  if category_id and not str(category_id).isdigit():
    resolved = await client.resolve_category_code(category_id)
    category_id = str(resolved) if resolved else ""

  # vendorUserId: Wing 로그인 ID (seller_id 사용)
  vendor_user_id = ""
  if account:
    vendor_user_id = account.seller_id or ""

  # 반품지 코드 조회 (API에서 동적 획득)
  return_center_code = ""
  try:
    rc_result = await client._call_api(
      "GET",
      f"/v2/providers/openapi/apis/api/v4/vendors/{vendor_id}/returnShippingCenters",
    )
    rc_data = rc_result.get("data", {})
    rc_content = rc_data.get("content", []) if isinstance(rc_data, dict) else []
    if rc_content:
      rc = rc_content[0]
      return_center_code = rc.get("returnCenterCode", "")
      # 반품지 주소 정보도 추출
      addrs = rc.get("placeAddresses", [])
      if addrs:
        addr = addrs[0]
  except Exception:
    pass

  # 출고지 코드 조회
  outbound_code = ""
  try:
    ob_result = await client._call_api(
      "GET",
      f"/v2/providers/marketplace_openapi/apis/api/v1/vendor/shipping-place/outbound",
      params={"pageNum": "1", "pageSize": "10"},
    )
    ob_content = ob_result.get("content", []) if isinstance(ob_result, dict) else []
    if ob_content:
      outbound_code = str(ob_content[0].get("outboundShippingPlaceCode", ""))
  except Exception:
    pass

  data = CoupangClient.transform_product(
    product, category_id,
    return_center_code=return_center_code,
    outbound_shipping_place_code=outbound_code,
  )
  data["vendorId"] = vendor_id
  data["vendorUserId"] = vendor_user_id or vendor_id

  # 반품지 실제 주소 정보 덮어쓰기
  if return_center_code and rc_content:
    addrs = rc_content[0].get("placeAddresses", [])
    if addrs:
      addr = addrs[0]
      data["returnZipCode"] = addr.get("returnZipCode", "")
      data["returnAddress"] = addr.get("returnAddress", "")
      data["returnAddressDetail"] = addr.get("returnAddressDetail", "")
      data["companyContactNumber"] = addr.get("companyContactNumber", "")
  result = await client.register_product(data)

  # 쿠팡 응답에서 sellerProductId 추출 (data 필드에 숫자로 반환)
  seller_product_id = ""
  if isinstance(result, dict):
    inner = result.get("data", {})
    if isinstance(inner, dict):
      seller_product_id = str(inner.get("data", ""))
    elif inner:
      seller_product_id = str(inner)

  return {
    "success": True,
    "message": "쿠팡 등록 성공",
    "data": {"sellerProductId": seller_product_id} if seller_product_id else result,
  }


async def _handle_11st(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None,
) -> dict[str, Any]:
  """11번가 상품 등록."""
  from backend.domain.samba.proxy.elevenst import ElevenstClient

  # 계정 객체에서 인증 정보 우선 사용
  api_key = ""
  if account:
    api_key = account.api_key or ""

  # fallback: Settings 테이블
  if not api_key:
    creds = await _get_setting(session, "store_11st")
    if creds and isinstance(creds, dict):
      api_key = creds.get("apiKey", "")

  if not api_key:
    return {"success": False, "message": "11번가 API Key가 비어있습니다. 설정에서 해당 계정을 수정 후 저장해주세요."}

  # 카테고리 코드가 숫자가 아니면 (경로 문자열이면) 빈값 처리
  cat_code = category_id
  if cat_code and not cat_code.isdigit():
    cat_code = ""

  if not cat_code:
    return {"success": False, "message": "11번가 카테고리 코드가 없습니다. 카테고리 매핑을 설정해주세요."}

  client = ElevenstClient(api_key)
  account_settings = (account.additional_fields or {}) if account else {}
  xml_data = ElevenstClient.transform_product(product, cat_code, settings=account_settings)
  result = await client.register_product(xml_data)
  return {"success": True, "message": "11번가 등록 성공", "data": result}


async def _handle_lotteon(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None,
) -> dict[str, Any]:
  """롯데ON 상품 등록 (롯데ON Open API)."""
  from backend.domain.samba.proxy.lotteon import LotteonClient

  # 계정 객체에서 인증 정보 우선 사용
  api_key = ""
  if account:
    extras = account.additional_fields or {}
    api_key = extras.get("apiKey", "") or account.api_key or ""

  # fallback: Settings 테이블
  if not api_key:
    creds = await _get_setting(session, "store_lotteon")
    if creds and isinstance(creds, dict):
      api_key = creds.get("apiKey", "")

  if not api_key:
    return {"success": False, "message": "롯데ON API Key가 비어있습니다. 설정에서 해당 계정을 수정 후 저장해주세요."}

  client = LotteonClient(api_key)
  # 거래처 정보 자동 획득 (trGrpCd, trNo)
  await client.test_auth()

  # 출고지/배송비정책/회수지 번호를 계정 또는 Settings에서 전달
  product = dict(product)
  extras: dict[str, Any] = {}
  if account:
    extras = account.additional_fields or {}
  if not extras.get("owhpNo"):
    creds = await _get_setting(session, "store_lotteon")
    if creds and isinstance(creds, dict):
      extras = {**creds, **extras}
  product["owhp_no"] = extras.get("owhpNo", "")
  product["dv_cst_pol_no"] = extras.get("dvCstPolNo", "")
  product["rtrp_no"] = extras.get("rtrpNo", "")

  data = LotteonClient.transform_product(
    product, category_id, client.tr_grp_cd or "SR", client.tr_no
  )
  result = await client.register_product(data)
  return {"success": True, "message": "롯데ON 등록 성공", "data": result}


async def _handle_lottehome(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None,
) -> dict[str, Any]:
  """롯데홈쇼핑 상품 등록."""
  from backend.domain.samba.proxy.lottehome import LotteHomeClient

  creds = await _get_setting(session, "lottehome_credentials")
  if not creds or not isinstance(creds, dict):
    creds = await _get_setting(session, "store_lottehome")
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "롯데홈쇼핑 설정이 없습니다."}

  user_id = creds.get("userId", "")
  password = creds.get("password", "")
  agnc_no = creds.get("agncNo", "")
  env = creds.get("env", "test")

  client = LotteHomeClient(user_id, password, agnc_no, env)
  goods_data = _transform_for_lottehome(product, category_id)
  result = await client.register_goods(goods_data)
  return {"success": True, "message": "롯데홈쇼핑 등록 성공", "data": result}


async def _handle_gsshop(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None,
) -> dict[str, Any]:
  """GS샵 상품 등록."""
  from backend.domain.samba.proxy.gsshop import GsShopClient

  creds = await _get_setting(session, "gsshop_credentials")
  if not creds or not isinstance(creds, dict):
    creds = await _get_setting(session, "store_gsshop")
  # account의 additional_fields에서 fallback
  if (not creds or not isinstance(creds, dict)) and account:
    extra = getattr(account, "additional_fields", None) or {}
    if extra.get("supCd") or extra.get("aesKey") or extra.get("apiKeyProd") or extra.get("apiKeyDev"):
      creds = extra
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "GS샵 설정이 없습니다."}

  sup_cd = creds.get("supCd", "") or creds.get("storeId", "") or creds.get("vendorId", "")
  # account.seller_id fallback (계정에 supCd가 seller_id로 저장된 경우)
  if not sup_cd and account:
    sup_cd = getattr(account, "seller_id", "") or ""
  aes_key = creds.get("aesKey", "") or creds.get("apiKeyProd", "") or creds.get("apiKeyDev", "")
  sub_sup_cd = creds.get("subSupCd", "")
  env = "prod" if creds.get("apiKeyProd") else creds.get("env", "dev")

  # 정책에서 GS샵 마켓마진율 조회
  gs_margin_rate = 0
  policy_id = product.get("applied_policy_id")
  if policy_id:
    from backend.domain.samba.policy.repository import SambaPolicyRepository
    policy_repo = SambaPolicyRepository(session)
    policy = await policy_repo.get_async(policy_id)
    if policy and policy.market_policies:
      gs_policy = policy.market_policies.get("GS샵", {})
      gs_margin_rate = gs_policy.get("gsMarginRate", 0)

  client = GsShopClient(sup_cd, aes_key, sub_sup_cd, env)
  goods_data = _transform_for_gsshop(product, category_id, gs_margin_rate)
  result = await client.register_goods(goods_data)

  # GS샵 API 응답 검증 — HTTP 200이지만 본문에 fail/401 포함 가능
  data = result.get("data", {})
  if isinstance(data, dict):
    # result: "fail" 체크 (GS샵은 HTTP 200 + body에 에러 반환)
    if data.get("result") == "fail":
      msg = data.get("message", "") or data.get("code", "") or "등록 실패"
      return {"success": False, "message": f"GS샵 등록 실패: {msg}", "data": data}
    result_code = data.get("resultCode", "")
    if result_code and result_code != "00" and result_code != "SUCCESS":
      msg = data.get("resultMessage", "") or data.get("message", "") or f"resultCode={result_code}"
      return {"success": False, "message": f"GS샵 등록 실패: {msg}", "data": data}

  return {"success": True, "message": "GS샵 등록 성공", "data": result}


async def _handle_ssg(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None,
) -> dict[str, Any]:
  """SSG(신세계몰) 상품 등록."""
  from backend.domain.samba.proxy.ssg import SSGClient

  creds = await _get_setting(session, "store_ssg")
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "SSG 설정이 없습니다."}

  api_key = creds.get("apiKey", "")
  if not api_key:
    return {"success": False, "message": "SSG 인증키가 비어있습니다."}

  store_id = creds.get("storeId", "6004")
  client = SSGClient(api_key, site_no=store_id)

  # 배송비/주소 인프라 데이터 자동 조회
  infra = await client.fetch_infra()
  logger.info(f"[SSG] 인프라 조회 완료: {list(infra.keys())}")

  data = client.transform_product(product, category_id, infra=infra)
  result = await client.register_product(data)

  # SSG API 응답 검증
  result_data = result.get("data", {})
  if isinstance(result_data, dict):
    res = result_data.get("result", {})
    if isinstance(res, dict):
      code = res.get("resultCode", "")
      if code and str(code) != "00" and str(code) != "SUCCESS":
        # resultDesc에 상세 에러 포함 — resultMessage("FAIL")보다 우선
        msg = res.get("resultDesc", "") or res.get("resultMessage", "") or f"resultCode={code}"
        return {"success": False, "message": f"SSG 등록 실패: {msg}", "data": result_data}

  return {"success": True, "message": "SSG 등록 성공", "data": result}


async def _handle_kream(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None,
) -> dict[str, Any]:
  """KREAM 매도 입찰 등록."""
  from backend.domain.samba.proxy.kream import KreamClient

  token = await _get_setting(session, "kream_token") or ""
  cookie = await _get_setting(session, "kream_cookie") or ""
  if not token and not cookie:
    creds = await _get_setting(session, "store_kream")
    if creds and isinstance(creds, dict):
      token = creds.get("token", "")

  if not token:
    return {"success": False, "message": "KREAM 인증 정보가 없습니다."}

  client = KreamClient(token=str(token), cookie=str(cookie))
  kream_data = product.get("kream_data") or {}
  product_id = kream_data.get("product_id", "")
  if not product_id:
    return {"success": False, "message": "KREAM 상품 ID가 없습니다."}

  # 사이즈별 매도 입찰
  options = product.get("options") or []
  sale_type = "auction"
  results = []
  for opt in options:
    size = opt.get("size", "") or opt.get("name", "")
    price = int(opt.get("price", product.get("sale_price", 0)))
    if size and price:
      r = await client.create_ask(product_id, size, price, sale_type)
      results.append(r)

  if not results:
    # 단일 상품
    price = int(product.get("sale_price", 0))
    r = await client.create_ask(product_id, "ONE_SIZE", price, sale_type)
    results.append(r)

  return {"success": True, "message": f"KREAM {len(results)}건 입찰 등록", "data": results}


# ═══════════════════════════════════════════════
# 데이터 변환 헬퍼
# ═══════════════════════════════════════════════


def _transform_for_lottehome(product: dict[str, Any], category_id: str) -> dict[str, Any]:
  """수집 상품 → 롯데홈쇼핑 형식 변환."""
  return {
    "goods_nm": product.get("name", ""),
    "sel_price": str(int(product.get("sale_price", 0))),
    "disp_ctgr_no": category_id,
    "brand_nm": product.get("brand", ""),
    "goods_img_url": (product.get("images") or [""])[0],
    "goods_detail": product.get("detail_html", "") or f"<p>{product.get('name', '')}</p>",
    "as_info": "상세페이지 참조",
    "rtn_exch_info": "상세페이지 참조",
  }


def _transform_for_gsshop(product: dict[str, Any], category_id: str, gs_margin_rate: int = 0) -> dict[str, Any]:
  """수집 상품 → GS샵 형식 변환."""
  images = product.get("images") or []
  data: dict[str, Any] = {
    "prdNm": product.get("name", ""),
    "brndNm": product.get("brand", ""),
    "selPrc": int(product.get("sale_price", 0)),
    "dispCtgrNo": category_id,
    "prdCntntListCntntUrlNm": images[0] if images else "",
    "mobilBannerImgUrl": images[0] if images else "",
    "prdDetailCntnt": product.get("detail_html", "") or f"<p>{product.get('name', '')}</p>",
  }
  # MD 협의 마켓마진율 (필수)
  if gs_margin_rate:
    data["supMgnRt"] = gs_margin_rate
  return data


# ═══════════════════════════════════════════════
# 마켓 핸들러 매핑
# ═══════════════════════════════════════════════


async def _handle_ebay(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None,
) -> dict[str, Any]:
  """eBay 상품 등록 (stub — API 연동 시 구현)."""
  return {"success": False, "message": "eBay API 연동이 아직 구현되지 않았습니다. 설정에서 API 키를 등록하면 자동으로 활성화됩니다."}


async def _handle_lazada(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None,
) -> dict[str, Any]:
  """Lazada 상품 등록 (stub)."""
  return {"success": False, "message": "Lazada API 연동이 아직 구현되지 않았습니다."}


async def _handle_qoo10(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None,
) -> dict[str, Any]:
  """Qoo10 상품 등록 (stub)."""
  return {"success": False, "message": "Qoo10 API 연동이 아직 구현되지 않았습니다."}


async def _handle_shopee(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None,
) -> dict[str, Any]:
  """Shopee 상품 등록 (stub)."""
  return {"success": False, "message": "Shopee API 연동이 아직 구현되지 않았습니다."}


async def _handle_shopify(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None,
) -> dict[str, Any]:
  """Shopify 상품 등록 (stub)."""
  return {"success": False, "message": "Shopify API 연동이 아직 구현되지 않았습니다."}


async def _handle_zoom(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None,
) -> dict[str, Any]:
  """Zum(줌) 상품 등록 (stub)."""
  return {"success": False, "message": "Zum(줌) API 연동이 아직 구현되지 않았습니다."}


MARKET_HANDLERS = {
  "smartstore": _handle_smartstore,
  "coupang": _handle_coupang,
  "11st": _handle_11st,
  "lotteon": _handle_lotteon,
  "ssg": _handle_ssg,
  "lottehome": _handle_lottehome,
  "gsshop": _handle_gsshop,
  "kream": _handle_kream,
  "ebay": _handle_ebay,
  "lazada": _handle_lazada,
  "qoo10": _handle_qoo10,
  "shopee": _handle_shopee,
  "shopify": _handle_shopify,
  "zoom": _handle_zoom,
}

# 지원 마켓 목록 (프론트엔드에서 참조)
SUPPORTED_MARKETS = list(MARKET_HANDLERS.keys())

# 미지원 마켓 (공개 API 없음 — 파트너 계약 또는 연동솔루션 필요)
UNSUPPORTED_MARKETS = ["gmarket", "auction", "homeand", "hmall"]


# ═══════════════════════════════════════════════
# 마켓 상품 삭제/판매중지
# ═══════════════════════════════════════════════


async def delete_from_market(
  session: AsyncSession,
  market_type: str,
  product: dict[str, Any],
  account: Any = None,
) -> dict[str, Any]:
  """마켓에서 상품 판매중지/삭제.

  품절 감지 시 호출되어 마켓에 등록된 상품을 내린다.
  각 마켓 API에 판매중지 메서드가 있으면 호출하고,
  없으면 재고 0 업데이트로 대체한다.
  """
  try:
    handler = MARKET_DELETE_HANDLERS.get(market_type)
    if not handler:
      # 삭제 핸들러 미구현 마켓 — 로그만 남김
      logger.warning(f"[디스패처] {market_type} 삭제 핸들러 미구현, 건너뜀")
      return {"success": True, "message": f"{market_type} 삭제 핸들러 미구현 (건너뜀)"}
    return await handler(session, product, account=account)
  except Exception as exc:
    logger.error(f"[디스패처] {market_type} 상품 삭제 실패: {exc}")
    return {"success": False, "message": f"{market_type} 삭제 실패: {str(exc)}"}


async def _delete_smartstore(
  session: AsyncSession, product: dict[str, Any], account: Any = None,
) -> dict[str, Any]:
  """스마트스토어 상품 판매중지."""
  from backend.domain.samba.proxy.smartstore import SmartStoreClient

  # 계정 객체에서 인증 정보 우선 사용
  client_id = ""
  client_secret = ""
  if account:
    extras = getattr(account, "additional_fields", None) or {}
    client_id = extras.get("clientId", "") or getattr(account, "api_key", "") or ""
    client_secret = extras.get("clientSecret", "") or getattr(account, "api_secret", "") or ""

  # fallback: Settings 테이블
  if not client_id or not client_secret:
    creds = await _get_setting(session, "store_smartstore")
    if creds and isinstance(creds, dict):
      client_id = client_id or creds.get("clientId", "")
      client_secret = client_secret or creds.get("clientSecret", "")

  if not client_id or not client_secret:
    return {"success": False, "message": "스마트스토어 인증 정보 없음"}

  client = SmartStoreClient(client_id, client_secret)
  # 판매중지: statusType을 SUSPENSION으로 업데이트
  product_no = product.get("market_product_no", {}).get("smartstore", "")
  if product_no:
    try:
      await client.update_product(product_no, {
        "originProduct": {"statusType": "SUSPENSION"}
      })
      return {"success": True, "message": "스마트스토어 판매중지 완료"}
    except Exception as e:
      return {"success": False, "message": f"판매중지 실패: {e}"}
  return {"success": True, "message": "스마트스토어 상품번호 없음 (건너뜀)"}


async def _delete_coupang(
  session: AsyncSession, product: dict[str, Any], account: Any = None,
) -> dict[str, Any]:
  """쿠팡 상품 판매중지 (재고 0 업데이트)."""
  from backend.domain.samba.proxy.coupang import CoupangClient

  creds = await _get_setting(session, "store_coupang")
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "쿠팡 설정 없음"}

  product_no = product.get("market_product_no", {}).get("coupang", "")
  if product_no:
    client = CoupangClient(creds.get("accessKey", ""), creds.get("secretKey", ""))
    try:
      await client.update_product(product_no, {"sellerProductName": product.get("name", ""), "statusType": "STOP"})
      return {"success": True, "message": "쿠팡 판매중지 완료"}
    except Exception as e:
      return {"success": False, "message": f"판매중지 실패: {e}"}
  return {"success": True, "message": "쿠팡 상품번호 없음 (건너뜀)"}


async def _delete_lottehome(
  session: AsyncSession, product: dict[str, Any], account: Any = None,
) -> dict[str, Any]:
  """롯데홈쇼핑 판매중지."""
  from backend.domain.samba.proxy.lottehome import LotteHomeClient

  creds = await _get_setting(session, "lottehome_credentials")
  if not creds or not isinstance(creds, dict):
    creds = await _get_setting(session, "store_lottehome")
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "롯데홈쇼핑 설정 없음"}

  product_no = product.get("market_product_no", {}).get("lottehome", "")
  if product_no:
    client = LotteHomeClient(
      creds.get("userId", ""), creds.get("password", ""),
      creds.get("agncNo", ""), creds.get("env", "test"),
    )
    try:
      await client.update_sale_status(product_no, "02")  # 02 = 판매중지
      return {"success": True, "message": "롯데홈쇼핑 판매중지 완료"}
    except Exception as e:
      return {"success": False, "message": f"판매중지 실패: {e}"}
  return {"success": True, "message": "롯데홈쇼핑 상품번호 없음 (건너뜀)"}


async def _delete_gsshop(
  session: AsyncSession, product: dict[str, Any], account: Any = None,
) -> dict[str, Any]:
  """GS샵 판매중지."""
  from backend.domain.samba.proxy.gsshop import GsShopClient

  creds = await _get_setting(session, "gsshop_credentials")
  if not creds or not isinstance(creds, dict):
    creds = await _get_setting(session, "store_gsshop")
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "GS샵 설정 없음"}

  product_no = product.get("market_product_no", {}).get("gsshop", "")
  if product_no:
    client = GsShopClient(
      creds.get("supCd", "") or creds.get("storeId", "") or creds.get("vendorId", ""),
      creds.get("aesKey", "") or creds.get("apiKeyProd", "") or creds.get("apiKeyDev", ""),
      creds.get("subSupCd", ""),
      "prod" if creds.get("apiKeyProd") else creds.get("env", "dev"),
    )
    try:
      await client.update_sale_status(product_no, "02")  # 02 = 판매중지
      return {"success": True, "message": "GS샵 판매중지 완료"}
    except Exception as e:
      return {"success": False, "message": f"판매중지 실패: {e}"}
  return {"success": True, "message": "GS샵 상품번호 없음 (건너뜀)"}


# 마켓별 삭제 핸들러 매핑
MARKET_DELETE_HANDLERS: dict[str, Any] = {
  "smartstore": _delete_smartstore,
  "coupang": _delete_coupang,
  "lottehome": _delete_lottehome,
  "gsshop": _delete_gsshop,
  # 11st, lotteon, ssg, kream — 삭제 API 미구현 (향후 추가)
}
