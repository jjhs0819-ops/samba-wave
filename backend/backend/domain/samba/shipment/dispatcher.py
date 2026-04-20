"""마켓 전송 디스패처 — 플러그인 기반.

모든 18개 마켓이 플러그인으로 등록되어 있으므로
레거시 인라인 핸들러는 제거되었다.
삭제/판매중지 핸들러는 아직 플러그인 미전환이므로 유지.
"""

from __future__ import annotations

from typing import Any, Callable, Coroutine

from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.forbidden.repository import SambaSettingsRepository
from backend.utils.logger import logger


# ═══════════════════════════════════════════════
# 공통 헬퍼
# ═══════════════════════════════════════════════


async def _get_setting(session: AsyncSession, key: str) -> Any:
    """samba_settings 테이블에서 설정값 조회."""
    repo = SambaSettingsRepository(session)
    row = await repo.find_by_async(key=key)
    if row:
        return row.value
    return None


async def _safe_delete(
    market_name: str,
    market_key: str,
    product: dict[str, Any],
    api_call: Callable[[str], Coroutine],
) -> dict[str, Any]:
    """마켓 삭제 공통 래퍼 — 상품번호 확인 + try/except 처리.

    Args:
      market_name: 로그/메시지용 마켓 이름 (예: "스마트스토어")
      market_key: market_product_no 딕셔너리 키 (예: "smartstore")
      product: 상품 딕셔너리
      api_call: product_no를 받아 삭제 API를 호출하는 코루틴
    """
    product_no = product.get("market_product_no", {}).get(market_key, "")
    if not product_no:
        return {"success": False, "message": f"{market_name} 상품번호 없음 (건너뜀)"}
    try:
        await api_call(product_no)
        return {"success": True, "message": f"{market_name} 삭제 완료"}
    except Exception as e:
        logger.error(f"[{market_name}] 삭제 실패: {e}")
        return {"success": False, "message": f"삭제 실패: {e}", "error_detail": str(e)}


# ═══════════════════════════════════════════════
# 검증 / 디스패치 (플러그인 기반)
# ═══════════════════════════════════════════════


def validate_transform(market_type: str, product: dict) -> list[str]:
    """전송 전 필수필드 누락 검사 → 누락 필드명 리스트 반환."""
    from backend.domain.samba.plugins import MARKET_PLUGINS

    plugin = MARKET_PLUGINS.get(market_type)
    if not plugin:
        return [f"미지원 마켓: {market_type}"]
    return [f for f in plugin.required_fields if not product.get(f)]


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
    from backend.domain.samba.plugins import MARKET_PLUGINS

    plugin = MARKET_PLUGINS.get(market_type)
    if not plugin:
        return {"success": False, "message": f"미지원 마켓: {market_type}"}

    # 필수필드 검증
    missing = [f for f in plugin.required_fields if not product.get(f)]
    if missing:
        return {
            "success": False,
            "error_type": "schema_changed",
            "message": f"필수필드 누락: {', '.join(missing)}",
        }

    try:
        return await plugin.handle(
            session,
            product,
            category_id,
            account=account,
            existing_no=existing_product_no,
        )
    except Exception as e:
        logger.error(f"[디스패처] {market_type} 전송 예외: {e}")
        return {"success": False, "message": str(e)}


# ═══════════════════════════════════════════════
# 마켓 목록
# ═══════════════════════════════════════════════


def get_supported_markets() -> list[str]:
    """플러그인 기반 지원 마켓 목록."""
    from backend.domain.samba.plugins import MARKET_PLUGINS

    return list(MARKET_PLUGINS.keys())


SUPPORTED_MARKETS = get_supported_markets()

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
            return {
                "success": False,
                "message": f"{market_type} 삭제 핸들러 미구현 (건너뜀)",
            }
        return await handler(session, product, account=account)
    except Exception as exc:
        logger.error(f"[디스패처] {market_type} 상품 삭제 실패: {exc}")
        return {"success": False, "message": f"{market_type} 삭제 실패: {str(exc)}"}


async def _delete_smartstore(
    session: AsyncSession,
    product: dict[str, Any],
    account: Any = None,
) -> dict[str, Any]:
    """스마트스토어 상품 삭제."""
    from backend.domain.samba.proxy.smartstore import SmartStoreClient

    # 계정 객체에서 인증 정보 우선 사용
    client_id = ""
    client_secret = ""
    if account:
        extras = getattr(account, "additional_fields", None) or {}
        client_id = extras.get("clientId", "") or getattr(account, "api_key", "") or ""
        client_secret = (
            extras.get("clientSecret", "") or getattr(account, "api_secret", "") or ""
        )

    # fallback: Settings 테이블
    if not client_id or not client_secret:
        creds = await _get_setting(session, "store_smartstore")
        if creds and isinstance(creds, dict):
            client_id = client_id or creds.get("clientId", "")
            client_secret = client_secret or creds.get("clientSecret", "")

    if not client_id or not client_secret:
        return {"success": False, "message": "스마트스토어 인증 정보 없음"}

    from backend.domain.samba.proxy.smartstore import SmartStoreApiError

    client = SmartStoreClient(client_id, client_secret)
    product_no = product.get("market_product_no", {}).get("smartstore", "")
    if not product_no:
        return {"success": False, "message": "스마트스토어 상품번호 없음 (건너뜀)"}

    async def _soldout_fallback(target_no: str, original_err: str) -> dict[str, Any]:
        """삭제 불가 시 전 옵션 재고 0 품절 폴백 (order.py 패턴 차용)."""
        logger.warning(
            f"[스마트스토어] 삭제 실패({original_err[:120]}) → 품절 폴백 시도: {target_no}"
        )
        try:
            existing = await client.get_product(target_no)
            origin = existing.get("originProduct", {})
            for k in ["productNo", "channelProducts", "regDate", "modifiedDate"]:
                origin.pop(k, None)
            origin["stockQuantity"] = 0
            opt_info = (origin.get("detailAttribute", {}).get("optionInfo")) or {}
            # SmartStore GET 응답은 optionCombinations 키 사용 (transform_product와 동일)
            combos = opt_info.get("optionCombinations") or opt_info.get(
                "combinations", []
            )
            zeroed = 0
            for combo in combos:
                combo["stockQuantity"] = 0
                combo["usable"] = False
                zeroed += 1
            put_data: dict[str, Any] = {"originProduct": origin}
            if "smartstoreChannelProduct" in existing:
                put_data["smartstoreChannelProduct"] = existing[
                    "smartstoreChannelProduct"
                ]
            await client.update_product(target_no, put_data)
            logger.info(
                f"[스마트스토어] 품절 폴백 완료: {target_no} (옵션 {zeroed}개 재고0+usable=False)"
            )
            return {
                "success": True,
                "soldout_fallback": True,
                "message": f"품절 처리 완료 (옵션 {zeroed}개)",
            }
        except Exception as fb_err:
            logger.error(f"[스마트스토어] 품절 폴백도 실패: {fb_err}")
            return {
                "success": False,
                "message": f"삭제 실패: {original_err} / 품절 폴백 실패: {fb_err}",
            }

    try:
        await client.delete_product(product_no)
        return {"success": True, "message": "스마트스토어 삭제 완료"}
    except SmartStoreApiError as e:
        err_str = str(e)
        if "HTTP 404" in err_str:
            logger.info(
                f"[스마트스토어] 상품 {product_no} 이미 삭제됨 (404) → 성공 처리"
            )
            return {"success": True, "message": "스마트스토어 삭제 완료 (이미 삭제됨)"}
        # 채널번호로 잘못 호출된 경우 — sellerManagementCode로 originProductNo 역조회
        style_code = product.get("style_code", "") or product.get("styleCode", "")
        if style_code:
            logger.warning(
                f"[스마트스토어] 삭제 실패({err_str[:80]}) → sellerManagementCode({style_code})로 origin 역조회 시도"
            )
            found = await client.find_by_management_code(style_code)
            if found:
                origin_no = str(
                    found.get("originProductNo")
                    or found.get("originProduct", {}).get("id", "")
                    or ""
                )
                if origin_no and origin_no != product_no:
                    logger.info(
                        f"[스마트스토어] origin 역조회 성공: {product_no} → {origin_no}, 재시도"
                    )
                    try:
                        await client.delete_product(origin_no)
                        return {
                            "success": True,
                            "message": f"스마트스토어 삭제 완료 (origin={origin_no})",
                        }
                    except SmartStoreApiError as e2:
                        if "HTTP 404" in str(e2):
                            return {
                                "success": True,
                                "message": "스마트스토어 삭제 완료 (이미 삭제됨)",
                            }
                        # origin 번호로도 삭제 실패 → 품절 폴백
                        return await _soldout_fallback(origin_no, str(e2))
        # 삭제 실패 시 에러 종류 무관하게 품절 폴백 시도
        return await _soldout_fallback(product_no, err_str)


async def _delete_coupang(
    session: AsyncSession,
    product: dict[str, Any],
    account: Any = None,
) -> dict[str, Any]:
    """쿠팡 상품 삭제."""
    from backend.domain.samba.proxy.coupang import CoupangClient

    access_key = ""
    secret_key = ""
    vendor_id = ""
    if account:
        extras = getattr(account, "additional_fields", None) or {}
        access_key = (
            extras.get("accessKey", "") or getattr(account, "api_key", "") or ""
        )
        secret_key = (
            extras.get("secretKey", "") or getattr(account, "api_secret", "") or ""
        )
        vendor_id = (
            extras.get("vendorId", "") or getattr(account, "seller_id", "") or ""
        )

    if not access_key or not secret_key:
        creds = await _get_setting(session, "store_coupang")
        if creds and isinstance(creds, dict):
            access_key = access_key or creds.get("accessKey", "")
            secret_key = secret_key or creds.get("secretKey", "")
            vendor_id = vendor_id or creds.get("vendorId", "")

    if not access_key or not secret_key:
        return {"success": False, "message": "쿠팡 인증 정보 없음"}

    client = CoupangClient(access_key, secret_key, vendor_id)
    return await _safe_delete("쿠팡", "coupang", product, client.delete_product)


async def _delete_lottehome(
    session: AsyncSession,
    product: dict[str, Any],
    account: Any = None,
) -> dict[str, Any]:
    """롯데홈쇼핑 상품 삭제 (영구중단)."""
    from backend.domain.samba.proxy.lottehome import LotteHomeClient

    creds = await _get_setting(session, "lottehome_credentials")
    if not creds or not isinstance(creds, dict):
        creds = await _get_setting(session, "store_lottehome")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "롯데홈쇼핑 설정 없음"}

    client = LotteHomeClient(
        creds.get("userId", ""),
        creds.get("password", ""),
        creds.get("agncNo", ""),
        creds.get("env", "test"),
    )
    # 30 = 영구중단
    return await _safe_delete(
        "롯데홈쇼핑",
        "lottehome",
        product,
        lambda pno: client.update_sale_status(pno, "30"),
    )


async def _delete_gsshop(
    session: AsyncSession,
    product: dict[str, Any],
    account: Any = None,
) -> dict[str, Any]:
    """GS샵 상품 삭제 (판매 종료)."""
    from datetime import datetime, timezone

    from backend.domain.samba.proxy.gsshop import GsShopClient

    creds = await _get_setting(session, "gsshop_credentials")
    if not creds or not isinstance(creds, dict):
        creds = await _get_setting(session, "store_gsshop")
    if (not creds or not isinstance(creds, dict)) and account:
        extra = getattr(account, "additional_fields", None) or {}
        if (
            extra.get("supCd")
            or extra.get("aesKey")
            or extra.get("apiKeyProd")
            or extra.get("apiKeyDev")
        ):
            creds = extra
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "GS샵 설정 없음"}

    sup_cd = (
        creds.get("supCd", "") or creds.get("storeId", "") or creds.get("vendorId", "")
    )
    if not sup_cd and account:
        sup_cd = getattr(account, "seller_id", "") or ""
    client = GsShopClient(
        sup_cd,
        creds.get("aesKey", "")
        or creds.get("apiKeyProd", "")
        or creds.get("apiKeyDev", ""),
        creds.get("subSupCd", ""),
        "prod" if creds.get("apiKeyProd") else creds.get("env", "dev"),
    )
    # 판매 종료일을 현재로 설정하여 즉시 판매 종료
    past = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return await _safe_delete(
        "GS샵",
        "gsshop",
        product,
        lambda pno: client.update_sale_status(pno, past),
    )


async def _delete_11st(
    session: AsyncSession,
    product: dict[str, Any],
    account: Any = None,
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

    client = ElevenstClient(api_key)
    return await _safe_delete("11번가", "11st", product, client.delete_product)


async def _delete_lotteon(
    session: AsyncSession,
    product: dict[str, Any],
    account: Any = None,
) -> dict[str, Any]:
    """롯데ON 상품 판매중지 — 플러그인 delete() 위임."""
    from backend.domain.samba.plugins.markets.lotteon import LotteonPlugin

    product_no = product.get("market_product_no", {}).get("lotteon", "")
    if not product_no:
        return {"success": False, "message": "롯데ON 상품번호 없음 (건너뜀)"}
    plugin = LotteonPlugin()
    return await plugin.delete(session, product_no, account)


async def _delete_ssg(
    session: AsyncSession,
    product: dict[str, Any],
    account: Any = None,
) -> dict[str, Any]:
    """SSG(신세계몰) 상품 삭제."""
    from backend.domain.samba.proxy.ssg import SSGClient

    creds = await _get_setting(session, "store_ssg")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "SSG 설정 없음"}

    api_key = creds.get("apiKey", "")
    if not api_key:
        return {"success": False, "message": "SSG 인증키 없음"}

    store_id = creds.get("storeId", SSGClient.DEFAULT_SITE_NO)
    client = SSGClient(api_key, site_no=store_id)
    return await _safe_delete("SSG", "ssg", product, client.delete_product)


async def _delete_cafe24(
    session: AsyncSession,
    product: dict[str, Any],
    account: Any = None,
) -> dict[str, Any]:
    """카페24 상품 완전 삭제 — 플러그인 delete() 위임."""
    from backend.domain.samba.plugins.markets.cafe24 import Cafe24Plugin

    product_no = product.get("market_product_no", {}).get("cafe24", "")
    if not product_no:
        return {"success": True, "message": "카페24 상품번호 없음 (건너뜀)"}
    plugin = Cafe24Plugin()
    return await plugin.delete(session, product_no, account)


async def _delete_playauto(
    session: AsyncSession,
    product: dict[str, Any],
    account: Any = None,
) -> dict[str, Any]:
    """플레이오토 마켓삭제 — DB에서만 제거 (완전삭제 API 없음, API 호출 불필요)."""
    return {"success": True, "message": "플레이오토: DB 제거 완료"}


# 마켓별 삭제 핸들러 매핑
MARKET_DELETE_HANDLERS: dict[str, Any] = {
    "smartstore": _delete_smartstore,
    "coupang": _delete_coupang,
    "11st": _delete_11st,
    "lotteon": _delete_lotteon,
    "ssg": _delete_ssg,
    "lottehome": _delete_lottehome,
    "gsshop": _delete_gsshop,
    "cafe24": _delete_cafe24,
    "playauto": _delete_playauto,
}
