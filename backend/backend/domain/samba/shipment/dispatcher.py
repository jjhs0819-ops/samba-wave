"""마켓 디스패처 - 마켓 타입에 따라 실제 API 호출을 라우팅.

각 마켓의 설정은 samba_settings 테이블에 store_{market_type} 키로 저장되어 있다.
수집 상품 데이터를 각 마켓 형식으로 변환하여 실제 API를 호출한다.
"""

from __future__ import annotations

import re
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
  "toss": ["name", "sale_price"],
  "rakuten": ["name", "sale_price"],
  "amazon": ["name", "sale_price"],
  "buyma": ["name", "sale_price"],
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
  existing_product_no: str = "",
) -> dict[str, Any]:
  """마켓 타입에 따라 상품 등록/수정 API를 호출.

  Args:
    session: DB 세션
    market_type: 마켓 구분
    product: SambaCollectedProduct 딕셔너리
    category_id: 대상 마켓 카테고리 코드
    account: SambaMarketAccount 객체 (계정별 인증 정보)
    existing_product_no: 기존 마켓 상품번호 (있으면 수정, 없으면 신규등록)

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

  # 플러그인 우선 호출 — 플러그인이 등록된 마켓은 플러그인으로 처리
  from backend.domain.samba.plugins import MARKET_PLUGINS
  plugin = MARKET_PLUGINS.get(market_type)
  if plugin:
    missing_plugin = [f for f in plugin.required_fields if not product.get(f)]
    if missing_plugin:
      return {
        "success": False,
        "error_type": "schema_changed",
        "message": f"필수필드 누락: {', '.join(missing_plugin)}",
      }
    try:
      return await plugin.handle(
        session, product, category_id,
        account=account, existing_no=existing_product_no,
      )
    except Exception as e:
      logger.error(f"[디스패처] 플러그인 {market_type} 실패: {e}")
      return {"success": False, "message": str(e)}

  # 기존 레거시 코드 유지 (폴백)
  try:
    handler = MARKET_HANDLERS.get(market_type)
    if not handler:
      return {
        "success": False,
        "error_type": "unsupported",
        "message": f"지원하지 않는 마켓: {market_type}",
      }
    return await handler(session, product, category_id, account=account, existing_product_no=existing_product_no)
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
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """스마트스토어 상품 등록/수정."""
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

  # 이미지 업로드 스킵 여부 (기존 상품 수정 시)
  skip_image = product.get("_skip_image_upload", False) and bool(existing_product_no)

  naver_images = []
  detail_html = product.get("detail_html", "")
  # 프로토콜 없는 이미지 URL 보정 (src="//... → src="https://...)
  if detail_html:
    detail_html = re.sub(r'(src=["\'])\/\/', r'\1https://', detail_html)

  import asyncio as _aio
  import httpx as _httpx

  # 동시 4장 업로드 + 공유 httpx 클라이언트 (커넥션 풀 재사용)
  _upload_sem = _aio.Semaphore(4)
  _dl_client = _httpx.AsyncClient(timeout=30, follow_redirects=True)
  _ul_client = _httpx.AsyncClient(timeout=30)

  async def _upload_safe(url: str) -> str | None:
    # 프로토콜 없는 URL 보정 (//image.msscdn.net/... → https://image.msscdn.net/...)
    if url.startswith("//"):
      url = "https:" + url
    async with _upload_sem:
      try:
        return await client.upload_image_from_url(url, _dl_client=_dl_client, _ul_client=_ul_client)
      except Exception as e:
        logger.warning(f"[스마트스토어] 이미지 업로드 실패: {e}")
        return None

  # 이미지 업로드 함수 (404 → 신규등록 시 재사용)
  async def _upload_images() -> tuple[list[str], str]:
    imgs_raw = product.get("images") or []
    detail_src_urls: list[str] = []
    dhtml = product.get("detail_html", "")
    if dhtml:
      img_pat = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)
      all_srcs = img_pat.findall(dhtml)
      detail_src_urls = list(dict.fromkeys(u for u in all_srcs if "naver.net" not in u and "pstatic.net" not in u))
    all_urls = list(imgs_raw[:5]) + detail_src_urls
    all_res = await _aio.gather(*[_upload_safe(url) for url in all_urls])
    tc = min(len(imgs_raw), 5)
    uploaded = [r for r in all_res[:tc] if r]
    for orig, naver_url in zip(detail_src_urls, all_res[tc:]):
      if naver_url:
        dhtml = dhtml.replace(orig, naver_url)
    return uploaded, dhtml

  # product_copy 준비 (계정/정책 설정 주입)
  product_copy = dict(product)

  if account:
    extras = account.additional_fields or {}
    if extras.get("asPhone"):
      product_copy["_as_phone"] = extras["asPhone"]
    if extras.get("asMessage"):
      product_copy["_as_message"] = extras["asMessage"]
    if extras.get("returnSafeguard") in (True, "true", "True"):
      product_copy["_return_safeguard"] = True
    naver_shopping = extras.get("naverShopping", "true")
    product_copy["_naver_shopping"] = naver_shopping in (True, "true", "True")
    if extras.get("returnFee"):
      product_copy["_return_fee"] = int(extras["returnFee"])
    if extras.get("exchangeFee"):
      product_copy["_exchange_fee"] = int(extras["exchangeFee"])
    if extras.get("jejuFee"):
      product_copy["_jeju_fee"] = int(extras["jejuFee"])
    if extras.get("stockQuantity"):
      product_copy["_stock_quantity"] = int(extras["stockQuantity"])
      logger.info(f"[스마트스토어] 계정 재고수량 설정: {extras['stockQuantity']}")
    if extras.get("multiPurchaseDiscount") in (True, "true"):
      product_copy["_multi_purchase"] = True
      if extras.get("multiPurchaseQty"):
        product_copy["_multi_purchase_qty"] = int(extras["multiPurchaseQty"])
      if extras.get("multiPurchaseRate"):
        product_copy["_multi_purchase_rate"] = int(extras["multiPurchaseRate"])
    product_copy["_purchase_point"] = extras.get("purchasePointEnabled") in (True, "true")
    if extras.get("purchasePointRate"):
      product_copy["_purchase_point_rate"] = int(extras["purchasePointRate"])
    product_copy["_review_point"] = extras.get("reviewPointEnabled") in (True, "true")
    if extras.get("reviewTextPoint"):
      product_copy["_review_text_point"] = int(extras["reviewTextPoint"])
    if extras.get("reviewPhotoPoint"):
      product_copy["_review_photo_point"] = int(extras["reviewPhotoPoint"])
    if extras.get("reviewMonthTextPoint"):
      product_copy["_review_month_text_point"] = int(extras["reviewMonthTextPoint"])
    if extras.get("reviewMonthPhotoPoint"):
      product_copy["_review_month_photo_point"] = int(extras["reviewMonthPhotoPoint"])
    if extras.get("reviewPhotoUrl"):
      product_copy["_review_photo_url"] = extras["reviewPhotoUrl"]
    if extras.get("discountRate"):
      product_copy["_discount_rate"] = int(extras["discountRate"])

  # 재고제한: 정책에서 읽기
  policy_id = product.get("applied_policy_id")
  if policy_id:
    from backend.domain.samba.policy.repository import SambaPolicyRepository
    policy_repo = SambaPolicyRepository(session)
    _policy = await policy_repo.get_async(policy_id)
    if _policy:
      pr = _policy.pricing or {}
      mp = (_policy.market_policies or {}).get("스마트스토어", {})
      shipping = int(mp.get("shippingCost") or pr.get("shippingCost") or 0)
      if shipping > 0:
        product_copy["_delivery_fee_type"] = "PAID"
        product_copy["_delivery_base_fee"] = shipping
      if mp.get("maxStock"):
        product_copy["_max_stock"] = mp["maxStock"]

  # 가격/재고만 업데이트 시 이미지+카탈로그 조회 모두 스킵
  if skip_image and existing_product_no:
    logger.info("[스마트스토어] 가격/재고 모드 → 이미지/카탈로그/브랜드/속성 조회 스킵")
  else:
    # ── 이미지 업로드 + 카탈로그/브랜드/속성 조회 동시 실행 ──
    style_code = product_copy.get("style_code", "")
    if not style_code:
      code_match = re.search(r'[A-Z]{2,}[\dA-Z]{4,}', product_copy.get("name", ""))
      if code_match:
        style_code = code_match.group()

    brand_name = product_copy.get("brand", "")
    mfr_name = product_copy.get("manufacturer", "") or brand_name

    async def _search_catalog():
      if style_code:
        return await client.search_catalog(style_code, category_id=str(category_id))
      return None

    async def _search_brand():
      if brand_name:
        return await client.search_brand(brand_name)
      return None

    async def _search_mfr():
      if mfr_name:
        return await client.search_manufacturer(mfr_name)
      return None

    async def _get_cat_attrs():
      return await client.get_category_attributes(category_id)

    async def _get_cert_infos():
      return await client.get_category_certification_infos(category_id)

    # 이미지 URL 수집
    images_raw = product.get("images") or []
    detail_img_urls: list[str] = []
    if detail_html:
      img_pattern = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)
      all_src_urls = img_pattern.findall(detail_html)
      detail_img_urls = list(dict.fromkeys(
        url for url in all_src_urls
        if "naver.net" not in url and "pstatic.net" not in url
      ))

    all_img_urls = list(images_raw[:5]) + detail_img_urls

    async def _upload_all_images():
      """대표 + 상세 이미지 통합 업로드."""
      return await _aio.gather(*[_upload_safe(url) for url in all_img_urls])

    # 이미지 업로드 + 5개 API 조회 동시 실행
    img_results, catalog, brand_id, mfr_id, cat_attrs, cert_infos = await _aio.gather(
      _upload_all_images(),
      _search_catalog(), _search_brand(), _search_mfr(), _get_cat_attrs(), _get_cert_infos(),
    )

    # 이미지 결과 반영
    thumb_count = min(len(images_raw), 5)
    naver_images = [r for r in img_results[:thumb_count] if r]
    if naver_images:
      product_copy["images"] = naver_images
    if detail_img_urls:
      detail_map = img_results[thumb_count:]
      replaced = 0
      for orig, naver_url in zip(detail_img_urls, detail_map):
        if naver_url:
          detail_html = detail_html.replace(orig, naver_url)
          replaced += 1
      product_copy["detail_html"] = detail_html
      logger.info(f"[스마트스토어] 이미지 업로드 완료 — 대표 {len(naver_images)}장, 상세 {replaced}장")
    elif naver_images:
      logger.info(f"[스마트스토어] 이미지 업로드 완료 — 대표 {len(naver_images)}장")

    # 카탈로그/브랜드 결과 반영
    if catalog:
      catalog_cat = str(catalog.get("categoryId", ""))
      if catalog_cat == str(category_id):
        product_copy["_catalog_model_id"] = catalog["modelId"]
      else:
        logger.info(f"[스마트스토어] 카탈로그 카테고리 불일치: 카탈로그={catalog_cat}, 상품={category_id} → modelId 스킵")
      product_copy["_brand_id"] = catalog["brandId"]
      product_copy["_manufacturer_id"] = catalog["manufacturerId"]
    if not product_copy.get("_brand_id") and brand_id:
      product_copy["_brand_id"] = brand_id
    if not product_copy.get("_manufacturer_id") and mfr_id:
      product_copy["_manufacturer_id"] = mfr_id
    if cat_attrs:
      product_copy["_category_attributes"] = cat_attrs
    if cert_infos:
      product_copy["_certification_infos"] = cert_infos
      logger.info(f"[스마트스토어] 카테고리 인증정보 {len(cert_infos)}개 → transform에 주입")

  # DB에서 스마트스토어 금지 태그 불러와 사전 필터링 (공백 제거 후 비교)
  try:
    banned_row = await _get_setting(session, "smartstore_banned_tags")
    if banned_row and isinstance(banned_row, list):
      banned_set = {w.lower().replace(" ", "") for w in banned_row}
      raw_tags = product_copy.get("tags") or []
      product_copy["tags"] = [t for t in raw_tags if t.startswith("__") or t.lower().replace(" ", "") not in banned_set]
  except Exception:
    pass

  # 옵션삭제어 로드
  try:
    from backend.domain.samba.forbidden.repository import SambaForbiddenWordRepository as _FWRepo
    _fw_repo = _FWRepo(session)
    _opt_del_words = await _fw_repo.list_active("option_deletion")
    if _opt_del_words:
      product_copy["_option_deletion_words"] = [w.word for w in _opt_del_words]
  except Exception:
    pass

  data = SmartStoreClient.transform_product(product_copy, category_id)

  # PUT은 전체 데이터가 필요 → 기존 상품 GET 후 변경 필드만 덮어쓰기
  if skip_image and existing_product_no:
    new_price = data.get("originProduct", {}).get("salePrice")
    new_stock = data.get("originProduct", {}).get("stockQuantity")
    new_opt = data.get("originProduct", {}).get("detailAttribute", {}).get("optionInfo")
    new_benefit = data.get("originProduct", {}).get("customerBenefit")
    try:
      existing_data = await client.get_product(existing_product_no)
      origin = existing_data.get("originProduct", {})
      # 읽기전용 필드 제거
      for k in ["productNo", "channelProducts", "regDate", "modifiedDate", "saleStartDate", "saleEndDate"]:
        origin.pop(k, None)
      # 가격/재고만 덮어쓰기
      if new_price is not None:
        origin["salePrice"] = new_price
      if new_stock is not None:
        origin["stockQuantity"] = new_stock
      if new_opt:
        origin.setdefault("detailAttribute", {})["optionInfo"] = new_opt
      if new_benefit:
        origin["customerBenefit"] = new_benefit
      data = {"originProduct": origin}
      if "smartstoreChannelProduct" in existing_data:
        data["smartstoreChannelProduct"] = existing_data["smartstoreChannelProduct"]
      logger.info(f"[스마트스토어] 가격/재고 업데이트 모드 (PUT): salePrice={new_price}, stockQuantity={new_stock}")
    except Exception as get_e:
      logger.error(f"[스마트스토어] 기존 상품 조회 실패: {get_e}")
      return {"success": False, "message": f"기존 상품 조회 실패: {get_e}"}
  else:
    # 전체 전송 시 디버그 로깅
    da = data.get("originProduct", {}).get("detailAttribute", {})
    logger.info(f"[스마트스토어] 전송 detailAttribute — modelName={da.get('modelName')}, brandId={da.get('brandId')}, brandName={da.get('brandName')}, mfr={da.get('manufacturerName')}, attrs={len(da.get('productAttributes', []))}개, cancelGuide={da.get('cancelGuide')}")

  # 기존 상품번호가 있으면 수정, 없으면 신규등록
  async def _try_send(d: dict[str, Any]) -> dict[str, Any]:
    if existing_product_no:
      try:
        logger.info(f"[스마트스토어] PUT 시도: origin={existing_product_no}, client_id={client_id[:8]}...")
        r = await client.update_product(existing_product_no, d)
        return {"success": True, "message": "스마트스토어 수정 성공", "data": r}
      except Exception as e:
        if "404" in str(e):
          # PATCH 404 → GET으로 상품 존재 여부 재확인
          product_exists = False
          try:
            await client.get_product(existing_product_no)
            product_exists = True
          except Exception:
            pass

          if product_exists:
            # 상품이 있는데 PATCH 404 → 등록 직후 검수 중. 재시도
            import asyncio as _retry_aio
            for _wait in [10, 20]:
              logger.warning(f"[스마트스토어] 상품 {existing_product_no} PUT 404이지만 GET 성공 → {_wait}초 후 재시도")
              await _retry_aio.sleep(_wait)
              try:
                r = await client.update_product(existing_product_no, d)
                return {"success": True, "message": "스마트스토어 수정 성공 (재시도)", "data": r}
              except Exception:
                continue
            # 재시도 모두 실패 — 상품번호 보존, 신규등록 차단
            logger.warning(f"[스마트스토어] PUT 재시도 2회 실패 — 검수 완료 후 다시 시도 필요")
            return {
              "success": False,
              "error_type": "patch_delayed",
              "message": f"상품 #{existing_product_no} 수정 실패 (검수 중). 잠시 후 다시 시도해주세요.",
            }

          # GET도 404 → 상품이 진짜 없음
          price_only = product.get("_price_stock_only", False)
          if skip_image or price_only:
            logger.warning(f"[스마트스토어] 수정 모드 상품 {existing_product_no} 404 → 신규등록 차단")
            return {
              "success": False,
              "error_type": "product_not_found",
              "message": f"상품 #{existing_product_no}이 스마트스토어에 없습니다. 강제삭제 후 재등록해주세요.",
              "_clear_product_no": True,
            }
          # 전체 전송 모드 + GET 404 → 상품이 삭제됨 → 신규등록 전환
          logger.warning(f"[스마트스토어] 상품 {existing_product_no} GET/PATCH 모두 404 → 신규등록 전환")
          try:
            full_copy = dict(product_copy)
            full_data = SmartStoreClient.transform_product(full_copy, category_id)
            r = await client.register_product(full_data)
            return {"success": True, "message": "스마트스토어 등록 성공 (404→신규전환)", "data": r, "_clear_product_no": True}
          except Exception as reg_e:
            logger.error(f"[스마트스토어] 404 → 신규등록 실패: {reg_e}")
            return {
              "success": False,
              "error_type": "product_not_found",
              "message": f"상품 #{existing_product_no} 수정/등록 실패: {reg_e}",
              "_clear_product_no": True,
            }
        raise
    else:
      r = await client.register_product(d)
      return {"success": True, "message": "스마트스토어 등록 성공", "data": r}

  # 태그사전 미등록 태그 사전 필터링 (누적 DB 기반)
  try:
    unregistered_row = await _get_setting(session, "smartstore_unregistered_tags")
    if unregistered_row and isinstance(unregistered_row, list):
      unreg_set = {w.lower() for w in unregistered_row}
      seo = data.get("originProduct", {}).get("detailAttribute", {}).get("seoInfo", {})
      old_tags = seo.get("sellerTags", [])
      if old_tags:
        filtered = [t for t in old_tags if t.get("text", "").lower() not in unreg_set]
        removed = len(old_tags) - len(filtered)
        if removed:
          logger.info(f"[스마트스토어] 미등록 태그 사전 필터링: {removed}개 제거")
          if filtered:
            data["originProduct"]["detailAttribute"]["seoInfo"]["sellerTags"] = filtered
          else:
            data["originProduct"]["detailAttribute"].pop("seoInfo", None)
  except Exception:
    pass

  try:
    result = await _try_send(data)
    return result
  except Exception as e:
    err_msg = str(e)
    # 등록불가 단어 에러 → 해당 태그 제거 후 재시도 + DB 저장
    if "등록불가" in err_msg:
      # 에러에서 금지 단어 추출: "등록불가인 단어(A,B,C)가"
      m = re.search(r"등록불가인 단어\(([^)]+)\)", err_msg)
      if m:
        banned = {w.strip().lower() for w in m.group(1).split(",")}
        # 1. DB에 금지 단어 누적 저장 (PK = key)
        try:
          repo = SambaSettingsRepository(session)
          row = await repo.find_by_async(key="smartstore_banned_tags")
          existing_banned: list[str] = []
          if row and isinstance(row.value, list):
            existing_banned = row.value
          merged = list(set(existing_banned + [w for w in banned]))
          if row:
            row.value = merged
            session.add(row)
          else:
            from backend.domain.samba.forbidden.model import SambaSettings
            session.add(SambaSettings(key="smartstore_banned_tags", value=merged))
          await session.commit()
          logger.info(f"[스마트스토어] 금지 태그 DB 저장: +{banned} (총 {len(merged)}개)")
        except Exception as save_err:
          logger.warning(f"[스마트스토어] 금지 태그 저장 실패: {save_err}")

        # 2. 상품 + 동일 그룹 전체 tags에서 금지 태그 일괄 제거
        try:
          from backend.domain.samba.collector.repository import SambaCollectedProductRepository
          from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
          from sqlmodel import select as _sel, col as _col
          product_id = product.get("id", "")
          if product_id:
            prod_repo = SambaCollectedProductRepository(session)
            prod_row = await prod_repo.get_async(product_id)
            if prod_row:
              # 같은 그룹 상품 전체 조회
              group_products = [prod_row]
              if prod_row.search_filter_id:
                grp_result = await session.exec(
                  _sel(_CP).where(_CP.search_filter_id == prod_row.search_filter_id)
                )
                group_products = grp_result.all()
              cleaned_count = 0
              for gp in group_products:
                if gp.tags:
                  cleaned = [t for t in gp.tags if t.startswith("__") or t.lower() not in banned]
                  if len(cleaned) != len(gp.tags):
                    await prod_repo.update_async(gp.id, tags=cleaned)
                    cleaned_count += 1
              await session.commit()
              logger.info(f"[스마트스토어] 그룹 {cleaned_count}개 상품에서 금지 태그 {banned} 제거")
        except Exception as tag_err:
          logger.warning(f"[스마트스토어] 그룹 태그 제거 실패: {tag_err}")

        # 3. sellerTags에서 해당 단어 제거 후 재시도 (공백 제거 후 비교)
        banned_nospace = {w.replace(" ", "") for w in banned}
        seo = data.get("originProduct", {}).get("detailAttribute", {}).get("seoInfo", {})
        old_tags = seo.get("sellerTags", [])
        if old_tags:
          new_tags = [t for t in old_tags if t.get("text", "").lower().replace(" ", "") not in banned_nospace]
          if new_tags:
            data["originProduct"]["detailAttribute"]["seoInfo"]["sellerTags"] = new_tags
          else:
            data["originProduct"]["detailAttribute"].pop("seoInfo", None)
          logger.info(f"[스마트스토어] 금지 태그 {banned} 제거 후 재시도 ({len(old_tags)}→{len(new_tags)}개)")
          return await _try_send(data)
    raise
  finally:
    # 공유 httpx 클라이언트 정리
    await _dl_client.aclose()
    await _ul_client.aclose()


async def _handle_coupang(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """쿠팡 상품 등록/수정."""
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

  # 계정 설정에서 AS 전화번호 주입
  product_copy = dict(product)
  if account:
    extras = account.additional_fields or {}
    if extras.get("asPhone"):
      product_copy["_as_phone"] = extras["asPhone"]

  data = CoupangClient.transform_product(
    product_copy, category_id,
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
  # 기존 상품번호가 있으면 수정, 없으면 신규등록
  if existing_product_no:
    result = await client.update_product(existing_product_no, data)
    return {
      "success": True,
      "message": "쿠팡 수정 성공",
      "data": {"sellerProductId": existing_product_no},
    }
  else:
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
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """11번가 상품 등록/수정."""
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

  # 기존 상품번호가 있으면 수정, 없으면 신규등록
  if existing_product_no:
    result = await client.update_product(existing_product_no, xml_data)
    return {"success": True, "message": "11번가 수정 성공", "data": result}
  else:
    result = await client.register_product(xml_data)
    return {"success": True, "message": "11번가 등록 성공", "data": result}


async def _handle_lotteon(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """롯데ON 상품 등록/수정 (롯데ON Open API)."""
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
  # 기존 상품번호가 있으면 수정, 없으면 신규등록
  try:
    if existing_product_no:
      data["selPrdNo"] = existing_product_no
      result = await client.update_product(data)
      return {"success": True, "message": "롯데ON 수정 성공", "data": result}
    else:
      result = await client.register_product(data)
      return {"success": True, "message": "롯데ON 등록 성공", "data": result}
  except Exception as e:
    action = "수정" if existing_product_no else "등록"
    return {"success": False, "message": f"롯데ON {action} 실패: {e}"}


async def _handle_lottehome(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """롯데홈쇼핑 상품 등록."""
  from backend.domain.samba.proxy.lottehome import LotteHomeClient

  # account.additional_fields 우선, settings fallback
  creds: dict[str, Any] = {}
  if account:
    extra = getattr(account, "additional_fields", None) or {}
    if extra.get("userId") or extra.get("password") or extra.get("agncNo"):
      creds = extra
    elif getattr(account, "seller_id", None):
      creds = {
        "userId": account.seller_id,
        "password": extra.get("password", ""),
        "agncNo": extra.get("agncNo", account.seller_id),
        "env": extra.get("env", "test"),
      }
  if not creds:
    creds = await _get_setting(session, "lottehome_credentials") or {}
  if not creds or not isinstance(creds, dict):
    creds = await _get_setting(session, "store_lottehome") or {}
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "롯데홈쇼핑 설정이 없습니다."}

  user_id = creds.get("userId", "") or (account.seller_id if account else "")
  password = creds.get("password", "")
  agnc_no = creds.get("agncNo", "")
  env = creds.get("env", "test")

  if not user_id or not password:
    return {"success": False, "message": "롯데홈쇼핑 userId/password가 없습니다."}

  client = LotteHomeClient(user_id, password, agnc_no, env)

  # 반품지/출고지/배송정책 자동 조회 (creds에 없으면)
  if not creds.get("corp_dlvp_sn") or not creds.get("corp_rls_pl_sn") or not creds.get("dlv_polc_no"):
    try:
      # 배송지(출고지/반품지) 조회
      places = await client.search_delivery_places()
      place_data = places.get("data", {})
      place_result = place_data.get("Result", place_data)
      place_list = place_result.get("DlvPlcList", place_result.get("DlvpList", {}))
      items = place_list.get("DlvPlcInfo", place_list.get("DlvpInfo", []))
      if isinstance(items, dict):
        items = [items]
      for item in (items if isinstance(items, list) else []):
        tp = item.get("dlvp_tp_cd", "")
        sn = item.get("corp_dlvp_sn", "")
        if tp in ("10", "30") and not creds.get("corp_dlvp_sn") and sn:
          creds["corp_dlvp_sn"] = sn  # 반품지
          logger.info(f"[롯데홈쇼핑] 반품지 자동 조회: {sn}")
        if tp in ("40", "50") and not creds.get("corp_rls_pl_sn") and sn:
          creds["corp_rls_pl_sn"] = sn  # 출고지
          logger.info(f"[롯데홈쇼핑] 출고지 자동 조회: {sn}")
      # 배송정책 조회
      if not creds.get("dlv_polc_no"):
        policies = await client.search_delivery_policies()
        pol_data = policies.get("data", {})
        pol_result = pol_data.get("Result", pol_data)
        pol_list = pol_result.get("DlvPolcList", pol_result.get("DlvPolcInfo", {}))
        pol_items = pol_list.get("DlvPolcInfo", []) if isinstance(pol_list, dict) else pol_list
        if isinstance(pol_items, dict):
          pol_items = [pol_items]
        if isinstance(pol_items, list) and pol_items:
          creds["dlv_polc_no"] = pol_items[0].get("dlv_polc_no", "")
          logger.info(f"[롯데홈쇼핑] 배송정책 자동 조회: {creds['dlv_polc_no']}")
    except Exception as e:
      logger.warning(f"[롯데홈쇼핑] 배송지/정책 자동 조회 실패: {e}")

  goods_data = _transform_for_lottehome(product, category_id, creds)
  result = await client.register_goods(goods_data)

  # 상품번호 추출
  g_data = result.get("data", {})
  g_result = g_data.get("GoodsResults", g_data.get("Result", g_data))
  goods_no = ""
  if isinstance(g_result, dict):
    goods_no = g_result.get("goods_no", "") or g_result.get("Result", "")
  return {"success": True, "message": "롯데홈쇼핑 등록 성공", "data": result, "goodsNo": goods_no}


async def _handle_gsshop(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
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
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """SSG(신세계몰) 상품 등록/수정."""
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

  # 기존 상품번호가 있으면 수정, 없으면 신규등록
  if existing_product_no:
    data["itemId"] = existing_product_no
    result = await client.update_product(data)
  else:
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

  action = "수정" if existing_product_no else "등록"
  return {"success": True, "message": f"SSG {action} 성공", "data": result}


async def _handle_kream(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
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


def _transform_for_lottehome(product: dict[str, Any], category_id: str, creds: dict[str, Any] | None = None) -> dict[str, Any]:
  """수집 상품 → 롯데홈쇼핑 API 형식 변환.

  API 문서: registApiGoodsInfo.lotte 파라미터 기준.
  """
  creds = creds or {}
  images = product.get("images") or []
  sale_price = int(product.get("sale_price", 0) or 0)
  # 판매가 끝자리 0 필수 (API 에러 1062)
  if sale_price % 10 != 0:
    sale_price = (sale_price // 10 + 1) * 10

  # 마진율 (정수, 1~99)
  margin_rate = int(product.get("margin_rate", 0) or 0)
  if margin_rate <= 0:
    margin_rate = 20

  # MD상품군번호 — 테스트: 24973(구두/신발), 카테고리코드가 없으면 creds에서 기본값
  md_gsgr_no = creds.get("md_gsgr_no", "") or category_id or ""

  # 품목코드 — 기본 102(구두/신발)
  ec_goods_artc_cd = creds.get("ec_goods_artc_cd", "102")

  data: dict[str, Any] = {
    # 필수
    "brnd_no": product.get("brand_code", "") or creds.get("brnd_no", "010565"),
    "goods_nm": product.get("name", ""),
    "md_gsgr_no": md_gsgr_no,
    "pur_shp_cd": "3",  # 위탁판매
    "sale_shp_cd": "10",  # 정상
    "sale_prc": str(sale_price),
    "mrgn_rt": str(margin_rate),
    "tdf_sct_cd": "1",  # 과세
    "disp_no": category_id or creds.get("disp_no", ""),
    "inv_mgmt_yn": "Y",
    "item_mgmt_yn": "N",
    "inv_qty": "999",
    "dlv_proc_tp_cd": "1",  # 업체배송
    "gift_pkg_yn": "N",
    "exch_rtgs_sct_cd": "20",  # 교환/반품 가능
    "dlv_mean_cd": "10",  # 택배
    "dlv_goods_sct_cd": "01",  # 일반상품
    "dlv_dday": "2",  # 배송기일 2일
    "byr_age_lmt_cd": "0",  # 나이제한 없음
    "dlv_polc_no": creds.get("dlv_polc_no", ""),
    "corp_dlvp_sn": creds.get("corp_dlvp_sn", ""),  # 반품지
    "corp_rls_pl_sn": creds.get("corp_rls_pl_sn", ""),  # 출고지
    "orpl_nm": product.get("origin", "") or "해외",
    "mfcp_nm": product.get("manufacturer", "") or product.get("brand", "") or "상세페이지 참조",
    "img_url": images[0] if images else "",
    "dtl_info_fcont": product.get("detail_html", "") or f"<p>{product.get('name', '')}</p>",
    "sum_pkg_psb_yn": "N",
    "ec_goods_artc_cd": ec_goods_artc_cd,
    "cdl_yn": "Y",  # 업체직송
    "cdl_goods_std": "30",  # 중형
    "prl_imp_yn": "N",
    "price_site_yn": "Y",
  }

  # 부가이미지 (최대 5장)
  for i, img in enumerate(images[1:6], start=1):
    data[f"img_url{i}"] = img

  # 품목별 항목정보 (구두/신발 102 기본값)
  if ec_goods_artc_cd == "102":
    data["10030"] = product.get("color", "") or "상세 이미지 참조"  # 색상
    data["10084"] = product.get("material", "") or "상세 이미지 참조"  # 주요소재
    data["10107"] = product.get("size_info", "") or "상세 이미지 참조"  # 크기
    data["10041_RD"] = "Y"  # 수입여부
    data["10041"] = "Y"
    data["10116"] = "품질보증기준에 따름"  # 품질보증기준
    data["10001"] = "상세페이지 참조"  # A/S 책임자/전화번호
  elif ec_goods_artc_cd == "101":
    data["10030"] = product.get("color", "") or "상세 이미지 참조"
    data["10035"] = "상세 이미지 참조"  # 세탁방법
    data["10041_RD"] = "Y"
    data["10041"] = "Y"
    data["10073"] = "상세 이미지 참조"  # 제조연월
    data["10116"] = "품질보증기준에 따름"
    data["10001"] = "상세페이지 참조"

  return data


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
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """eBay 상품 등록 (stub — API 연동 시 구현)."""
  return {"success": False, "message": "eBay API 연동이 아직 구현되지 않았습니다. 설정에서 API 키를 등록하면 자동으로 활성화됩니다."}


async def _handle_lazada(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """Lazada 상품 등록 (stub)."""
  return {"success": False, "message": "Lazada API 연동이 아직 구현되지 않았습니다."}


async def _handle_qoo10(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """Qoo10 상품 등록 (stub)."""
  return {"success": False, "message": "Qoo10 API 연동이 아직 구현되지 않았습니다."}


async def _handle_shopee(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """Shopee 상품 등록 (stub)."""
  return {"success": False, "message": "Shopee API 연동이 아직 구현되지 않았습니다."}


async def _handle_shopify(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """Shopify 상품 등록 (stub)."""
  return {"success": False, "message": "Shopify API 연동이 아직 구현되지 않았습니다."}


async def _handle_zoom(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """Zum(줌) 상품 등록 (stub)."""
  return {"success": False, "message": "Zum(줌) API 연동이 아직 구현되지 않았습니다."}


async def _handle_toss(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """토스 상품 등록/수정."""
  from backend.domain.samba.proxy.toss import TossClient, TossApiError

  access_key = ""
  secret_key = ""
  if account:
    extras = account.additional_fields or {}
    access_key = extras.get("apiKey", "") or account.api_key or ""
    secret_key = extras.get("apiSecret", "") or account.api_secret or ""

  if not access_key or not secret_key:
    return {"success": False, "message": "토스 API Key/Secret이 없습니다.", "error_type": "auth_failed"}

  client = TossClient(access_key, secret_key)
  settings = (account.additional_fields or {}) if account else {}
  payload = TossClient.transform_product(product, category_id, settings)

  try:
    if existing_product_no:
      result = await client.update_product(existing_product_no, payload)
    else:
      result = await client.register_product(payload)
    product_no = str(result.get("productId") or result.get("productNo") or result.get("id") or "")
    return {"success": True, "data": result, "productNo": product_no}
  except TossApiError as e:
    logger.error(f"[토스] 등록 실패: {e}")
    return {"success": False, "message": str(e), "error_type": "schema_changed"}
  except httpx.TimeoutException:
    return {"success": False, "message": "토스 API 타임아웃", "error_type": "network"}
  except Exception as e:
    logger.error(f"[토스] 예외: {e}")
    return {"success": False, "message": str(e), "error_type": "unknown"}


async def _handle_rakuten(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """라쿠텐 상품 등록/수정."""
  from backend.domain.samba.proxy.rakuten import RakutenClient, RakutenApiError

  service_secret = ""
  license_key = ""
  if account:
    extras = account.additional_fields or {}
    service_secret = extras.get("apiKey", "") or account.api_key or ""
    license_key = extras.get("apiSecret", "") or account.api_secret or ""

  if not service_secret or not license_key:
    return {"success": False, "message": "라쿠텐 serviceSecret/licenseKey가 없습니다.", "error_type": "auth_failed"}

  client = RakutenClient(service_secret, license_key)
  settings = (account.additional_fields or {}) if account else {}
  payload = RakutenClient.transform_product(product, category_id, settings)
  manage_number = payload.get("itemUrl") or product.get("id") or ""

  try:
    if existing_product_no:
      result = await client.update_product(existing_product_no, payload)
    else:
      result = await client.register_product(payload, manage_number)
    return {"success": True, "data": result, "productNo": manage_number}
  except RakutenApiError as e:
    logger.error(f"[라쿠텐] 등록 실패: {e}")
    return {"success": False, "message": str(e), "error_type": "schema_changed"}
  except httpx.TimeoutException:
    return {"success": False, "message": "라쿠텐 API 타임아웃", "error_type": "network"}
  except Exception as e:
    logger.error(f"[라쿠텐] 예외: {e}")
    return {"success": False, "message": str(e), "error_type": "unknown"}


async def _handle_amazon(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """아마존 상품 등록/수정."""
  from backend.domain.samba.proxy.amazon import AmazonClient, AmazonApiError

  refresh_token = ""
  client_id = ""
  client_secret = ""
  seller_id = ""
  region = "fe"
  if account:
    extras = account.additional_fields or {}
    refresh_token = extras.get("accessToken", "") or account.api_key or ""
    client_id = extras.get("clientId", "")
    client_secret = extras.get("clientSecret", "") or account.api_secret or ""
    seller_id = extras.get("storeId", "") or account.seller_id or ""
    region = extras.get("region", "fe")

  if not refresh_token or not client_id or not client_secret:
    return {"success": False, "message": "아마존 Refresh Token/Client ID/Secret이 없습니다.", "error_type": "auth_failed"}

  client = AmazonClient(refresh_token, client_id, client_secret, seller_id, region)
  settings = (account.additional_fields or {}) if account else {}
  payload = AmazonClient.transform_product(product, category_id, settings)
  sku = product.get("site_product_id") or product.get("id") or ""

  try:
    if existing_product_no:
      result = await client.update_product(existing_product_no, payload)
    else:
      result = await client.register_product(payload, sku)
    return {"success": True, "data": result, "productNo": sku}
  except AmazonApiError as e:
    logger.error(f"[아마존] 등록 실패: {e}")
    return {"success": False, "message": str(e), "error_type": "schema_changed"}
  except httpx.TimeoutException:
    return {"success": False, "message": "아마존 API 타임아웃", "error_type": "network"}
  except Exception as e:
    logger.error(f"[아마존] 예외: {e}")
    return {"success": False, "message": str(e), "error_type": "unknown"}


async def _handle_buyma(
  session: AsyncSession, product: dict[str, Any], category_id: str, account: Any = None, existing_product_no: str = "",
) -> dict[str, Any]:
  """바이마 상품 등록 — CSV 행 데이터 반환 (API 없음)."""
  from backend.domain.samba.proxy.buyma import BuymaClient

  settings = (account.additional_fields or {}) if account else {}
  client = BuymaClient(seller_id=settings.get("storeId", ""))

  try:
    result = await client.register_product(product, category_id)
    return {
      "success": True,
      "data": result,
      "productNo": product.get("id") or "",
      "message": result.get("message", ""),
    }
  except Exception as e:
    logger.error(f"[바이마] CSV 생성 실패: {e}")
    return {"success": False, "message": str(e), "error_type": "unknown"}


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
  "toss": _handle_toss,
  "rakuten": _handle_rakuten,
  "amazon": _handle_amazon,
  "buyma": _handle_buyma,
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
  """스마트스토어 상품 삭제."""
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
  product_no = product.get("market_product_no", {}).get("smartstore", "")
  if product_no:
    try:
      await client.delete_product(product_no)
      return {"success": True, "message": "스마트스토어 삭제 완료"}
    except Exception as e:
      return {"success": False, "message": f"삭제 실패: {e}"}
  return {"success": True, "message": "스마트스토어 상품번호 없음 (건너뜀)"}


async def _delete_coupang(
  session: AsyncSession, product: dict[str, Any], account: Any = None,
) -> dict[str, Any]:
  """쿠팡 상품 삭제."""
  from backend.domain.samba.proxy.coupang import CoupangClient

  access_key = ""
  secret_key = ""
  vendor_id = ""
  if account:
    extras = getattr(account, "additional_fields", None) or {}
    access_key = extras.get("accessKey", "") or getattr(account, "api_key", "") or ""
    secret_key = extras.get("secretKey", "") or getattr(account, "api_secret", "") or ""
    vendor_id = extras.get("vendorId", "") or getattr(account, "seller_id", "") or ""

  if not access_key or not secret_key:
    creds = await _get_setting(session, "store_coupang")
    if creds and isinstance(creds, dict):
      access_key = access_key or creds.get("accessKey", "")
      secret_key = secret_key or creds.get("secretKey", "")
      vendor_id = vendor_id or creds.get("vendorId", "")

  if not access_key or not secret_key:
    return {"success": False, "message": "쿠팡 인증 정보 없음"}

  product_no = product.get("market_product_no", {}).get("coupang", "")
  if product_no:
    client = CoupangClient(access_key, secret_key, vendor_id)
    try:
      await client.delete_product(product_no)
      return {"success": True, "message": "쿠팡 삭제 완료"}
    except Exception as e:
      return {"success": False, "message": f"삭제 실패: {e}"}
  return {"success": True, "message": "쿠팡 상품번호 없음 (건너뜀)"}


async def _delete_lottehome(
  session: AsyncSession, product: dict[str, Any], account: Any = None,
) -> dict[str, Any]:
  """롯데홈쇼핑 상품 삭제 (영구중단)."""
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
      await client.update_sale_status(product_no, "30")  # 30 = 영구중단
      return {"success": True, "message": "롯데홈쇼핑 삭제 완료"}
    except Exception as e:
      return {"success": False, "message": f"삭제 실패: {e}"}
  return {"success": True, "message": "롯데홈쇼핑 상품번호 없음 (건너뜀)"}


async def _delete_gsshop(
  session: AsyncSession, product: dict[str, Any], account: Any = None,
) -> dict[str, Any]:
  """GS샵 상품 삭제 (판매 종료)."""
  from datetime import datetime, timezone

  from backend.domain.samba.proxy.gsshop import GsShopClient

  creds = await _get_setting(session, "gsshop_credentials")
  if not creds or not isinstance(creds, dict):
    creds = await _get_setting(session, "store_gsshop")
  if (not creds or not isinstance(creds, dict)) and account:
    extra = getattr(account, "additional_fields", None) or {}
    if extra.get("supCd") or extra.get("aesKey") or extra.get("apiKeyProd") or extra.get("apiKeyDev"):
      creds = extra
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "GS샵 설정 없음"}

  product_no = product.get("market_product_no", {}).get("gsshop", "")
  if product_no:
    sup_cd = creds.get("supCd", "") or creds.get("storeId", "") or creds.get("vendorId", "")
    if not sup_cd and account:
      sup_cd = getattr(account, "seller_id", "") or ""
    client = GsShopClient(
      sup_cd,
      creds.get("aesKey", "") or creds.get("apiKeyProd", "") or creds.get("apiKeyDev", ""),
      creds.get("subSupCd", ""),
      "prod" if creds.get("apiKeyProd") else creds.get("env", "dev"),
    )
    try:
      # 판매 종료일을 과거로 설정하여 즉시 판매 종료
      past = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
      await client.update_sale_status(product_no, past)
      return {"success": True, "message": "GS샵 삭제 완료"}
    except Exception as e:
      return {"success": False, "message": f"삭제 실패: {e}"}
  return {"success": True, "message": "GS샵 상품번호 없음 (건너뜀)"}


async def _delete_11st(
  session: AsyncSession, product: dict[str, Any], account: Any = None,
) -> dict[str, Any]:
  """11번가 상품 삭제."""
  from backend.domain.samba.proxy.elevenst import ElevenstClient

  api_key = ""
  if account:
    api_key = getattr(account, "api_key", "") or ""
  if not api_key:
    creds = await _get_setting(session, "store_11st")
    if creds and isinstance(creds, dict):
      api_key = creds.get("apiKey", "")
  if not api_key:
    return {"success": False, "message": "11번가 인증 정보 없음"}

  product_no = product.get("market_product_no", {}).get("11st", "")
  if product_no:
    client = ElevenstClient(api_key)
    try:
      await client.delete_product(product_no)
      return {"success": True, "message": "11번가 삭제 완료"}
    except Exception as e:
      return {"success": False, "message": f"삭제 실패: {e}"}
  return {"success": True, "message": "11번가 상품번호 없음 (건너뜀)"}


async def _delete_lotteon(
  session: AsyncSession, product: dict[str, Any], account: Any = None,
) -> dict[str, Any]:
  """롯데ON 상품 삭제 (판매종료)."""
  from backend.domain.samba.proxy.lotteon import LotteonClient

  api_key = ""
  if account:
    extras = getattr(account, "additional_fields", None) or {}
    api_key = extras.get("apiKey", "") or getattr(account, "api_key", "") or ""
  if not api_key:
    creds = await _get_setting(session, "store_lotteon")
    if creds and isinstance(creds, dict):
      api_key = creds.get("apiKey", "")
  if not api_key:
    return {"success": False, "message": "롯데ON 인증 정보 없음"}

  product_no = product.get("market_product_no", {}).get("lotteon", "")
  if product_no:
    client = LotteonClient(api_key)
    await client.test_auth()
    try:
      await client.delete_product(product_no)
      return {"success": True, "message": "롯데ON 삭제 완료"}
    except Exception as e:
      return {"success": False, "message": f"삭제 실패: {e}"}
  return {"success": True, "message": "롯데ON 상품번호 없음 (건너뜀)"}


async def _delete_ssg(
  session: AsyncSession, product: dict[str, Any], account: Any = None,
) -> dict[str, Any]:
  """SSG(신세계몰) 상품 삭제."""
  from backend.domain.samba.proxy.ssg import SSGClient

  creds = await _get_setting(session, "store_ssg")
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "SSG 설정 없음"}

  api_key = creds.get("apiKey", "")
  if not api_key:
    return {"success": False, "message": "SSG 인증키 없음"}

  product_no = product.get("market_product_no", {}).get("ssg", "")
  if product_no:
    store_id = creds.get("storeId", "6004")
    client = SSGClient(api_key, site_no=store_id)
    try:
      await client.delete_product(product_no)
      return {"success": True, "message": "SSG 삭제 완료"}
    except Exception as e:
      return {"success": False, "message": f"삭제 실패: {e}"}
  return {"success": True, "message": "SSG 상품번호 없음 (건너뜀)"}


# 마켓별 삭제 핸들러 매핑
MARKET_DELETE_HANDLERS: dict[str, Any] = {
  "smartstore": _delete_smartstore,
  "coupang": _delete_coupang,
  "11st": _delete_11st,
  "lotteon": _delete_lotteon,
  "ssg": _delete_ssg,
  "lottehome": _delete_lottehome,
  "gsshop": _delete_gsshop,
}
