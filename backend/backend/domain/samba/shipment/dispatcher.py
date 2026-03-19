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
) -> dict[str, Any]:
  """마켓 타입에 따라 실제 상품 등록 API를 호출.

  Args:
    session: DB 세션
    market_type: 마켓 구분 (smartstore, coupang, 11st, gmarket, auction, lottehome, gsshop, kream 등)
    product: SambaCollectedProduct 딕셔너리
    category_id: 대상 마켓 카테고리 코드

  Returns:
    {"success": bool, "message": str, "data": Any}
  """
  # 전송 전 필수필드 사전 검증
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
    return await handler(session, product, category_id)
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
  session: AsyncSession, product: dict[str, Any], category_id: str
) -> dict[str, Any]:
  """스마트스토어 상품 등록."""
  from backend.domain.samba.proxy.smartstore import SmartStoreClient

  creds = await _get_setting(session, "store_smartstore")
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "스마트스토어 설정이 없습니다."}

  client_id = creds.get("clientId", "")
  client_secret = creds.get("clientSecret", "")
  if not client_id or not client_secret:
    return {"success": False, "message": "Client ID/Secret이 비어있습니다."}

  client = SmartStoreClient(client_id, client_secret)
  data = SmartStoreClient.transform_product(product, category_id)
  result = await client.register_product(data)
  return {"success": True, "message": "스마트스토어 등록 성공", "data": result}


async def _handle_coupang(
  session: AsyncSession, product: dict[str, Any], category_id: str
) -> dict[str, Any]:
  """쿠팡 상품 등록."""
  from backend.domain.samba.proxy.coupang import CoupangClient

  creds = await _get_setting(session, "store_coupang")
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "쿠팡 설정이 없습니다."}

  access_key = creds.get("accessKey", "")
  secret_key = creds.get("secretKey", "")
  vendor_id = creds.get("vendorId", "")
  if not access_key or not secret_key:
    return {"success": False, "message": "Access Key/Secret Key가 비어있습니다."}

  client = CoupangClient(access_key, secret_key, vendor_id)
  data = CoupangClient.transform_product(product, category_id)
  data["vendorId"] = vendor_id
  result = await client.register_product(data)
  return {"success": True, "message": "쿠팡 등록 성공", "data": result}


async def _handle_11st(
  session: AsyncSession, product: dict[str, Any], category_id: str
) -> dict[str, Any]:
  """11번가 상품 등록."""
  from backend.domain.samba.proxy.elevenst import ElevenstClient

  creds = await _get_setting(session, "store_11st")
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "11번가 설정이 없습니다."}

  api_key = creds.get("apiKey", "")
  if not api_key:
    return {"success": False, "message": "Open API Key가 비어있습니다."}

  client = ElevenstClient(api_key)
  xml_data = ElevenstClient.transform_product(product, category_id)
  result = await client.register_product(xml_data)
  return {"success": True, "message": "11번가 등록 성공", "data": result}


async def _handle_lotteon(
  session: AsyncSession, product: dict[str, Any], category_id: str
) -> dict[str, Any]:
  """롯데ON 상품 등록 (롯데ON Open API)."""
  from backend.domain.samba.proxy.lotteon import LotteonClient

  creds = await _get_setting(session, "store_lotteon")
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "롯데ON 설정이 없습니다."}

  api_key = creds.get("apiKey", "")
  if not api_key:
    return {"success": False, "message": "롯데ON API Key가 비어있습니다."}

  client = LotteonClient(api_key)
  # 거래처 정보 자동 획득
  await client.test_auth()
  data = LotteonClient.transform_product(
    product, category_id, client.tr_grp_cd or "SR", client.tr_no
  )
  result = await client.register_product(data)
  return {"success": True, "message": "롯데ON 등록 성공", "data": result}


async def _handle_lottehome(
  session: AsyncSession, product: dict[str, Any], category_id: str
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
  session: AsyncSession, product: dict[str, Any], category_id: str
) -> dict[str, Any]:
  """GS샵 상품 등록."""
  from backend.domain.samba.proxy.gsshop import GsShopClient

  creds = await _get_setting(session, "gsshop_credentials")
  if not creds or not isinstance(creds, dict):
    creds = await _get_setting(session, "store_gsshop")
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "GS샵 설정이 없습니다."}

  sup_cd = creds.get("supCd", "") or creds.get("vendorId", "")
  aes_key = creds.get("aesKey", "") or creds.get("apiKeyProd", "")
  sub_sup_cd = creds.get("subSupCd", "")
  env = creds.get("env", "dev")

  client = GsShopClient(sup_cd, aes_key, sub_sup_cd, env)
  goods_data = _transform_for_gsshop(product, category_id)
  result = await client.register_goods(goods_data)
  return {"success": True, "message": "GS샵 등록 성공", "data": result}


async def _handle_ssg(
  session: AsyncSession, product: dict[str, Any], category_id: str
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
  data = client.transform_product(product, category_id)
  result = await client.register_product(data)
  return {"success": True, "message": "SSG 등록 성공", "data": result}


async def _handle_kream(
  session: AsyncSession, product: dict[str, Any], category_id: str
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


def _transform_for_gsshop(product: dict[str, Any], category_id: str) -> dict[str, Any]:
  """수집 상품 → GS샵 형식 변환."""
  images = product.get("images") or []
  return {
    "prdNm": product.get("name", ""),
    "brndNm": product.get("brand", ""),
    "selPrc": int(product.get("sale_price", 0)),
    "dispCtgrNo": category_id,
    "prdCntntListCntntUrlNm": images[0] if images else "",
    "mobilBannerImgUrl": images[0] if images else "",
    "prdDetailCntnt": product.get("detail_html", "") or f"<p>{product.get('name', '')}</p>",
  }


# ═══════════════════════════════════════════════
# 마켓 핸들러 매핑
# ═══════════════════════════════════════════════


MARKET_HANDLERS = {
  "smartstore": _handle_smartstore,
  "coupang": _handle_coupang,
  "11st": _handle_11st,
  "lotteon": _handle_lotteon,
  "ssg": _handle_ssg,
  "lottehome": _handle_lottehome,
  "gsshop": _handle_gsshop,
  "kream": _handle_kream,
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
    return await handler(session, product)
  except Exception as exc:
    logger.error(f"[디스패처] {market_type} 상품 삭제 실패: {exc}")
    return {"success": False, "message": f"{market_type} 삭제 실패: {str(exc)}"}


async def _delete_smartstore(
  session: AsyncSession, product: dict[str, Any],
) -> dict[str, Any]:
  """스마트스토어 상품 판매중지."""
  from backend.domain.samba.proxy.smartstore import SmartStoreClient

  creds = await _get_setting(session, "store_smartstore")
  if not creds or not isinstance(creds, dict):
    return {"success": False, "message": "스마트스토어 설정 없음"}

  client = SmartStoreClient(creds.get("clientId", ""), creds.get("clientSecret", ""))
  # 판매중지: saleType을 SUSPENSION으로 업데이트
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
  session: AsyncSession, product: dict[str, Any],
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
  session: AsyncSession, product: dict[str, Any],
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
  session: AsyncSession, product: dict[str, Any],
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
      creds.get("supCd", "") or creds.get("vendorId", ""),
      creds.get("aesKey", "") or creds.get("apiKeyProd", ""),
      creds.get("subSupCd", ""), creds.get("env", "dev"),
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
