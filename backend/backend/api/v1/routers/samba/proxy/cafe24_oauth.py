"""카페24 OAuth 엔드포인트 — JWT 인증 불필요 (카페24 서버가 외부에서 콜백 호출)."""

from __future__ import annotations

import base64
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.utils.logger import logger

# JWT 예외 라우터 — app_factory.py에서 samba_auth 의존성 없이 등록
cafe24_oauth_router = APIRouter(prefix="/proxy", tags=["samba-proxy-cafe24-oauth"])


def _encode_cafe24_state(account_id: str, return_url: str) -> str:
    """카페24 OAuth state 생성 — account_id + return_url을 base64url로 인코딩."""
    payload = json.dumps({"a": account_id, "r": return_url}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cafe24_state(state: str) -> tuple[str, str]:
    """카페24 OAuth state 파싱 — (account_id, return_url) 반환.

    구버전 state(account_id 단독)도 호환.
    """
    try:
        padding = "=" * (-len(state) % 4)
        decoded = base64.urlsafe_b64decode((state + padding).encode("ascii")).decode(
            "utf-8"
        )
        data = json.loads(decoded)
        return data.get("a", ""), data.get("r", "")
    except Exception:
        # 구버전: state가 곧 account_id
        return state, ""


@cafe24_oauth_router.get("/cafe24/install")
async def cafe24_install(
    mall_id: str = Query(...),
    user_id: str = Query(...),
    timestamp: str = Query(...),
    shop_no: str = Query(default="1"),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """카페24 앱 설치 핸들러 — 테스트 실행/앱 설치 시 카페24가 호출하는 App URL 엔드포인트."""
    from fastapi.responses import RedirectResponse
    from sqlmodel import select
    from backend.domain.samba.account.model import SambaMarketAccount

    stmt = (
        select(SambaMarketAccount)
        .where(SambaMarketAccount.market_type == "cafe24")
        .where(SambaMarketAccount.is_active.is_(True))
        .limit(1)
    )
    result = await session.execute(stmt)
    account = result.scalars().first()

    if not account:
        return {
            "error": "카페24 계정이 없습니다. 쌈바웨이브 설정에서 먼저 계정을 등록해주세요."
        }

    extras = account.additional_fields or {}
    client_id = extras.get("clientId") or account.api_key or ""
    redirect_uri = extras.get("redirectUri", "")
    scope = "mall.read_application,mall.write_application,mall.read_product,mall.write_product,mall.read_category,mall.write_category,mall.read_collection,mall.write_collection,mall.read_supply,mall.write_supply,mall.read_order,mall.write_order,mall.read_community,mall.write_community,mall.read_customer,mall.write_customer,mall.read_notification,mall.write_notification,mall.read_design,mall.write_design,mall.read_shipping,mall.write_shipping"

    auth_url = (
        f"https://{mall_id}.cafe24api.com/api/v2/oauth/authorize"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&state={account.id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
    )
    logger.info(
        f"[카페24] 앱 설치 요청 — mall_id={mall_id}, user_id={user_id} → OAuth 리다이렉트"
    )
    return RedirectResponse(url=auth_url)


@cafe24_oauth_router.get("/cafe24/authorize")
async def cafe24_authorize(
    account_id: str,
    return_url: str = "",
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """카페24 OAuth 인증 URL 생성.

    프론트에서 이 URL을 받아 운영자가 브라우저에서 접속하면
    카페24 로그인 → 권한 승인 → Redirect URI로 code 전달.
    return_url: 콜백 후 리다이렉트할 프론트 URL (state에 인코딩됨).
    """
    from backend.domain.samba.account.repository import SambaMarketAccountRepository

    repo = SambaMarketAccountRepository(session)
    account = await repo.get_async(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")

    extras = account.additional_fields or {}
    client_id = extras.get("clientId") or account.api_key or ""
    mall_id = extras.get("mallId") or account.seller_id or ""
    redirect_uri = extras.get("redirectUri", "")

    if not client_id or not mall_id:
        raise HTTPException(
            status_code=400,
            detail="clientId 또는 mallId가 없습니다. 계정 설정을 확인해주세요.",
        )
    if not redirect_uri:
        raise HTTPException(
            status_code=400,
            detail="redirectUri가 없습니다. 계정 설정에서 redirectUri를 입력해주세요.",
        )

    state = _encode_cafe24_state(account_id, return_url)
    scope = "mall.read_application,mall.write_application,mall.read_product,mall.write_product,mall.read_category,mall.write_category,mall.read_collection,mall.write_collection,mall.read_supply,mall.write_supply,mall.read_order,mall.write_order,mall.read_community,mall.write_community,mall.read_customer,mall.write_customer,mall.read_notification,mall.write_notification,mall.read_design,mall.write_design,mall.read_shipping,mall.write_shipping"
    auth_url = (
        f"https://{mall_id}.cafe24api.com/api/v2/oauth/authorize"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&state={state}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
    )
    return {"auth_url": auth_url}


@cafe24_oauth_router.get("/cafe24/callback")
async def cafe24_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """카페24 OAuth 콜백 — code → access_token 교환 후 DB 저장."""
    from fastapi.responses import HTMLResponse, RedirectResponse
    from sqlalchemy.orm.attributes import flag_modified
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.proxy.cafe24 import Cafe24Client

    if error:
        msg = error_description or error
        logger.warning(f"[카페24] OAuth 에러 — error={error}, desc={error_description}")
        return HTMLResponse(
            content=f"""<html><body style="font-family:sans-serif;padding:40px;background:#1a1a2e;color:#fff">
<h2>카페24 OAuth 인증 실패</h2>
<p style="color:#ff6b6b">오류: {error}</p>
<p>{msg}</p>
<p style="color:#aaa;margin-top:20px">카페24 개발자센터에서 앱의 권한 스코프를 확인해주세요.</p>
<script>setTimeout(()=>window.close(),5000)</script>
</body></html>""",
            status_code=200,
        )

    if not code or not state:
        logger.warning("[카페24] OAuth 콜백 — code 또는 state 없음")
        return HTMLResponse(
            content="""<html><body style="font-family:sans-serif;padding:40px;background:#1a1a2e;color:#fff">
<h2>카페24 OAuth 인증 실패</h2>
<p style="color:#ff6b6b">인증 코드를 받지 못했습니다. 다시 시도해주세요.</p>
<script>setTimeout(()=>window.close(),3000)</script>
</body></html>""",
            status_code=200,
        )

    account_id, return_url = _decode_cafe24_state(state)

    repo = SambaMarketAccountRepository(session)
    account = await repo.get_async(account_id)
    if not account:
        raise HTTPException(
            status_code=404, detail=f"계정을 찾을 수 없습니다. account_id={account_id}"
        )

    extras = account.additional_fields or {}
    client_id = extras.get("clientId") or account.api_key or ""
    client_secret = extras.get("clientSecret") or account.api_secret or ""
    mall_id = extras.get("mallId") or account.seller_id or ""
    redirect_uri = extras.get("redirectUri", "")

    if not client_id or not client_secret or not mall_id:
        raise HTTPException(
            status_code=400, detail="clientId/clientSecret/mallId가 없습니다."
        )

    try:
        tokens = await Cafe24Client.exchange_code(
            mall_id=mall_id,
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=redirect_uri,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"토큰 교환 실패: {e}")

    # JSONB 변경을 SQLAlchemy가 감지하도록 flag_modified 명시 호출
    account.additional_fields = {
        **extras,
        "accessToken": tokens["access_token"],
        "refreshToken": tokens.get("refresh_token", ""),
    }
    flag_modified(account, "additional_fields")
    session.add(account)
    await session.commit()

    logger.info(f"[카페24] OAuth 완료 — account_id={account_id}, mall_id={mall_id}")

    target = return_url or "https://samba-wave-theta.vercel.app/samba/settings"
    sep = "&" if "?" in target else "?"
    return RedirectResponse(url=f"{target}{sep}cafe24=connected")
