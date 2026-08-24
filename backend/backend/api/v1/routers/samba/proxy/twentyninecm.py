"""29CM 프록시 라우터 — 확장앱이 수집한 로그인 쿠키 저장/조회.

원가(최대혜택가)는 상세 API 의 노출가를 쓰지만, 계정 기준 수집을 위해 쿠키를 싣는다.
쿠키는 소싱처 계정(자동로그인 기본계정)의 additional_fields 에 저장하고,
계정 매칭이 안 되면 SambaSettings 풀에만 저장한다(무신사와 같은 구조).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.utils.logger import logger

from ._helpers import _get_setting, _set_setting

router = APIRouter()
# 확장앱 전용 라우터 — JWT 면제(X-Api-Key 인증). main router 의 samba_auth 가
# 확장앱 호출(X-Api-Key만 전송)을 401 로 막기 때문에 분리한다(무신사 선례).
extension_router = APIRouter(tags=["samba-proxy-extension"])

SETTING_KEY = "twentyninecm_cookies"
ACCOUNT_FIELD = "twentyninecm_cookie"


class TwentyNineCMCookieRequest(BaseModel):
    cookie: str = ""
    # 계정 식별용 — 29CM 로그인 아이디(user-api /users/me 의 loginId) 또는 이메일
    loginId: Optional[str] = None
    email: Optional[str] = None
    expired: bool = False


@extension_router.post("/29cm/set-cookie")
async def set_29cm_cookie(
    request: Request,
    body: TwentyNineCMCookieRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """확장앱이 수집한 29CM 쿠키 저장 (확장앱 공용 규약: {site}/set-cookie).

    1) site_name=29CM 계정 중 username/memo 가 loginId/email 과 맞는 계정에 저장
    2) 매칭 실패 시 SambaSettings 풀에만 저장 (계정 미등록 인스턴스 대비)
    """
    from backend.api.v1.routers.samba.sourcing_account import _check_owner_device
    from backend.domain.samba.sourcing_account.repository import (
        SambaSourcingAccountRepository,
    )
    from backend.domain.samba.sourcing_account.service import (
        SambaSourcingAccountService,
    )

    # 포크 확장앱이 원본 백엔드로 쿠키를 미러 전송하는 누수 차단(무신사 선례)
    _check_owner_device(request)

    svc = SambaSourcingAccountService(SambaSourcingAccountRepository(write_session))
    accounts = await svc.list_accounts(site_name="29CM")

    key = (body.loginId or body.email or "").strip().lower()
    matched = None
    if key:
        for a in accounts:
            username = (a.username or "").strip().lower()
            memo = (a.memo or "").strip().lower()
            # 마스킹된 loginId(ede*****)도 접두 일치로 잡는다
            if username and (username == key or username.startswith(key.split("*")[0])):
                matched = a
                break
            if memo and memo == key:
                matched = a
                break

    if matched:
        extra = dict(matched.additional_fields or {})
        if body.expired:
            extra["cookie_expired"] = True
            extra["cookie_expired_at"] = datetime.now(timezone.utc).isoformat()
        else:
            extra[ACCOUNT_FIELD] = body.cookie
            extra["cookie_expired"] = False
            extra["cookie_updated_at"] = datetime.now(timezone.utc).isoformat()
        await svc.repo.update_async(matched.id, additional_fields=extra)
        logger.info(
            f"[29CM 쿠키] {matched.account_label}: "
            f"{'만료 처리' if body.expired else '갱신'}"
        )

    saved_pool = False
    if body.cookie and not body.expired:
        await _set_setting(write_session, SETTING_KEY, json.dumps([body.cookie]))
        saved_pool = True

    return {
        "ok": True,
        "matched": bool(matched),
        "accountLabel": matched.account_label if matched else None,
        "poolSaved": saved_pool,
    }


@router.get("/29cm/cookies")
async def get_29cm_cookie(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """저장된 29CM 쿠키 개수 조회 (값 자체는 노출하지 않는다)."""
    raw = await _get_setting(session, SETTING_KEY)
    cookies: list[str] = []
    if raw:
        try:
            val = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(val, list):
                cookies = [c for c in val if c]
        except (TypeError, ValueError):
            cookies = []
    return {"count": len(cookies), "hasCookie": bool(cookies)}
