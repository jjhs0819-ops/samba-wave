"""BUYMA PS-API OAuth 엔드포인트 — JWT 인증 불필요 (BUYMA가 외부에서 콜백 호출).

콜백 URL은 BUYMA Partners 앱 등록값과 일치해야 함:
  https://api.samba-wave.co.kr/api/v1/samba/buyma/oauth/callback
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.core.config import settings
from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.utils.logger import logger

# JWT 예외 라우터 — app_factory.py에서 samba_auth 의존성 없이 등록
buyma_oauth_router = APIRouter(prefix="/buyma/oauth", tags=["samba-proxy-buyma-oauth"])

# BUYMA Partners 앱에 등록한 고정 콜백 URL (일치 필수)
REDIRECT_URI = "https://api.samba-wave.co.kr/api/v1/samba/buyma/oauth/callback"


def _state_sig(payload: str) -> str:
    """state HMAC 서명 — account_id를 그대로 base64에 실으면 공격자가 임의
    계정ID로 조작한 state를 만들어 남의 계정에 자기 토큰을 심을 수 있다.
    jwt_secret_key 로 서명해 위조 시도를 콜백에서 즉시 거부한다."""
    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:16]


def _encode_state(account_id: str, return_url: str) -> str:
    payload = json.dumps(
        {"a": account_id, "r": return_url, "n": secrets.token_hex(8)},
        separators=(",", ":"),
    )
    signed = json.dumps({"p": payload, "s": _state_sig(payload)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(signed.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_state(state: str) -> tuple[str, str]:
    """서명 불일치·파싱 실패 시 빈 값 반환 — 호출부가 계정 없음으로 처리해 거부."""
    try:
        padding = "=" * (-len(state) % 4)
        decoded = base64.urlsafe_b64decode((state + padding).encode("ascii")).decode(
            "utf-8"
        )
        outer = json.loads(decoded)
        payload, sig = outer.get("p", ""), outer.get("s", "")
        if not payload or not hmac.compare_digest(sig, _state_sig(payload)):
            return "", ""
        data = json.loads(payload)
        return data.get("a", ""), data.get("r", "")
    except Exception:
        return "", ""


@buyma_oauth_router.get("/authorize")
async def buyma_authorize(
    account_id: str,
    return_url: str = "",
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """OAuth 인증 URL 생성. 프론트가 받아 운영자가 브라우저로 접속 → 승인 → 콜백."""
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.proxy.buyma import BuymaApiClient

    repo = SambaMarketAccountRepository(session)
    account = await repo.get_async(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")

    client_id = account.api_key or ""
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="client_id(API Key)가 없습니다. 계정 설정을 확인해주세요.",
        )
    sandbox = bool((account.additional_fields or {}).get("sandbox"))
    state = _encode_state(account_id, return_url)
    auth_url = BuymaApiClient.authorize_url(
        client_id, REDIRECT_URI, state, sandbox=sandbox
    )
    return {"auth_url": auth_url}


@buyma_oauth_router.get("/callback")
async def buyma_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """OAuth 콜백 — code → access_token 교환 후 oauth 컬럼에 저장."""
    from fastapi.responses import HTMLResponse, RedirectResponse

    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.proxy.buyma import BuymaApiClient

    if error:
        logger.warning(f"[바이마] OAuth 에러 — {error}: {error_description}")
        return HTMLResponse(
            content=f"""<html><body style="font-family:sans-serif;padding:40px;background:#1a1a2e;color:#fff">
<h2>BUYMA OAuth 인증 실패</h2><p style="color:#ff6b6b">{error}</p><p>{error_description or ""}</p>
<script>setTimeout(()=>window.close(),5000)</script></body></html>""",
            status_code=200,
        )
    if not code or not state:
        return HTMLResponse(
            content="""<html><body style="font-family:sans-serif;padding:40px;background:#1a1a2e;color:#fff">
<h2>BUYMA OAuth 인증 실패</h2><p style="color:#ff6b6b">인증 코드를 받지 못했습니다.</p>
<script>setTimeout(()=>window.close(),3000)</script></body></html>""",
            status_code=200,
        )

    account_id, return_url = _decode_state(state)
    repo = SambaMarketAccountRepository(session)
    account = await repo.get_async(account_id)
    if not account:
        raise HTTPException(
            status_code=404, detail=f"계정 없음 account_id={account_id}"
        )

    client_id = account.api_key or ""
    client_secret = account.api_secret or ""
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400, detail="client_id/client_secret이 없습니다."
        )
    sandbox = bool((account.additional_fields or {}).get("sandbox"))

    try:
        tokens = await BuymaApiClient.exchange_code(
            code, REDIRECT_URI, client_id, client_secret, sandbox=sandbox
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"토큰 교환 실패: {e}")

    account.oauth_access_token = tokens.get("access_token", "")
    account.oauth_refresh_token = tokens.get("refresh_token", "")
    session.add(account)
    await session.commit()
    logger.info(f"[바이마] OAuth 완료 — account_id={account_id} sandbox={sandbox}")

    target = return_url or "https://samba-wave-theta.vercel.app/samba/settings"
    sep = "&" if "?" in target else "?"
    return RedirectResponse(url=f"{target}{sep}buyma=connected")
