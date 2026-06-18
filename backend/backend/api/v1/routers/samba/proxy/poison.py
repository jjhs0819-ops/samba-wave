"""POIZON(포이즌) 프록시 라우터 — 인증 테스트 및 SKU 조회."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.tenant.middleware import get_optional_tenant_id
from backend.utils.logger import logger

from ._helpers import _get_setting, _set_setting

router = APIRouter(tags=["samba-proxy"])


@router.post("/poison/auth-test")
async def poison_auth_test(
    body: dict[str, Any],
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> dict[str, Any]:
    """POIZON 인증 테스트 — body 직접 전달 우선, 없으면 store_poison 폴백."""
    from backend.domain.samba.proxy.poison import PoisonClient

    def _pick_key(d: dict) -> str:
        return str(d.get("appKey") or d.get("app_key") or d.get("apiKey") or "").strip()

    def _pick_secret(d: dict) -> str:
        return str(
            d.get("appSecret") or d.get("app_secret") or d.get("apiSecret") or ""
        ).strip()

    # 1) body에 직접 전달된 값 우선
    app_key = _pick_key(body)
    app_secret = _pick_secret(body)

    # 2) 없으면 store_poison samba_settings 폴백
    if not app_key or not app_secret:
        creds = await _get_setting(session, "store_poison", tenant_id=tenant_id)
        if creds and isinstance(creds, dict):
            app_key = app_key or _pick_key(creds)
            app_secret = app_secret or _pick_secret(creds)

    if not app_key or not app_secret:
        return {"success": False, "message": "App Key 또는 App Secret이 없습니다."}

    client = PoisonClient(app_key=app_key, app_secret=app_secret)
    # Nike Air Force 1 공식 품번으로 카탈로그 조회 — 원시 응답 code 로 인증 판별.
    # query_sku_by_article_number 는 에러코드도 []로 반환하므로 직접 _post 호출해
    # POIZON 응답 code/msg 를 그대로 노출(권한 미승인 400010006 등을 거짓 성공으로 삼키지 않음).
    try:
        raw = await client._post(
            client.PATH_SKU_BY_ARTICLE,
            {
                "articleNumber": "315122-111",
                "region": client.region,
                "language": client.language,
            },
        )
    except Exception as e:
        logger.warning(f"[POIZON] 인증 테스트 호출 실패: {e}")
        return {"success": False, "message": f"POIZON API 호출 실패: {e}"}

    code = raw.get("code")
    msg = str(raw.get("msg") or raw.get("message") or "").strip()
    if code == 200:
        data = raw.get("data") or []
        count = len(data) if isinstance(data, list) else 0
        return {"success": True, "message": f"POIZON 인증 성공 (SKU {count}건)"}
    # 서명·키는 유효하나 API 권한 패키지(Default)가 아직 승인되지 않은 상태
    if str(code) == "400010006":
        return {
            "success": False,
            "message": "키·서명은 정상이나 API 권한 패키지(Default)가 아직 승인되지 않았습니다. POIZON 콘솔에서 권한 승인 후 다시 시도하세요.",
        }
    return {
        "success": False,
        "message": f"POIZON 인증 실패 (code={code}){f' — {msg}' if msg else ''}",
    }


@router.post("/poison/set-credentials")
async def poison_set_credentials(
    body: dict[str, Any],
    write_session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> dict[str, Any]:
    """POIZON App Key / App Secret 저장."""
    app_key = str(body.get("appKey") or body.get("apiKey") or "").strip()
    app_secret = str(body.get("appSecret") or body.get("apiSecret") or "").strip()
    if not app_key or not app_secret:
        return {
            "success": False,
            "message": "App Key와 App Secret을 모두 입력해주세요.",
        }

    existing = (
        await _get_setting(write_session, "store_poison", tenant_id=tenant_id) or {}
    )
    if not isinstance(existing, dict):
        existing = {}
    merged = {**existing, "apiKey": app_key, "apiSecret": app_secret}
    await _set_setting(write_session, "store_poison", merged, tenant_id=tenant_id)
    logger.info("[POIZON] App Key/Secret 저장 완료")
    return {"success": True, "message": "POIZON 인증 정보가 저장되었습니다."}
