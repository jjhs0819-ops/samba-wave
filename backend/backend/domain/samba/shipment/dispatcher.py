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
        return {"success": False, "message": f"삭제 실패: {e}"}


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

    client = SmartStoreClient(client_id, client_secret)
    return await _safe_delete(
        "스마트스토어", "smartstore", product, client.delete_product
    )


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


async def _delete_playauto(
    session: AsyncSession,
    product: dict[str, Any],
    account: Any = None,
) -> dict[str, Any]:
    """플레이오토 품절 처리 — EMP API soldout 호출 (완전삭제 API 없음)."""
    from backend.domain.samba.proxy.playauto import PlayAutoClient

    api_key = ""
    if account:
        api_key = getattr(account, "api_key", "") or ""
    if not api_key:
        creds = await _get_setting(session, "store_playauto")
        if creds and isinstance(creds, dict):
            api_key = creds.get("apiKey", "")
    if not api_key:
        return {"success": False, "message": "플레이오토 인증 정보 없음"}

    product_no = product.get("market_product_no", {}).get("playauto", "")
    if not product_no:
        return {"success": False, "message": "플레이오토 상품번호 없음 (건너뜀)"}

    client = PlayAutoClient(api_key)
    try:
        await client.soldout_product([product_no])
        return {"success": True, "message": "플레이오토 품절 처리 완료"}
    except Exception as e:
        logger.error(f"[플레이오토] 품절 처리 실패: {e}")
        return {"success": False, "message": f"품절 처리 실패: {e}"}


# 마켓별 삭제 핸들러 매핑
MARKET_DELETE_HANDLERS: dict[str, Any] = {
    "smartstore": _delete_smartstore,
    "coupang": _delete_coupang,
    "11st": _delete_11st,
    "lotteon": _delete_lotteon,
    "ssg": _delete_ssg,
    "lottehome": _delete_lottehome,
    "gsshop": _delete_gsshop,
    "playauto": _delete_playauto,
}
