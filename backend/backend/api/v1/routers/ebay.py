"""eBay Marketplace Account Deletion Notification 엔드포인트."""

import base64
import hashlib
import logging

import httpx
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import HTMLResponse

from backend.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ebay"])


@router.get("/ebay/deletion-notification")
async def ebay_deletion_challenge(
    challenge_code: str = Query(..., description="eBay challenge code"),
) -> Response:
    """eBay endpoint 검증 — challenge-response 응답.

    eBay가 엔드포인트 등록 시 GET 요청으로 challenge_code를 보내면
    SHA-256(challenge_code + verification_token + endpoint_url) 해시를 반환.

    환경변수(EBAY_DELETION_NOTIFICATION_URL, EBAY_VERIFICATION_TOKEN)가
    설정되어 있지 않으면 503을 반환 — 잘못된 해시로 응답해 검증 통과가 되는 사고 방지.
    """
    token = settings.ebay_verification_token
    url = settings.ebay_deletion_notification_url
    if not token or not url:
        logger.error(
            "[eBay] EBAY_VERIFICATION_TOKEN / EBAY_DELETION_NOTIFICATION_URL "
            "환경변수 미설정 — endpoint 비활성화 상태"
        )
        return Response(
            content='{"error":"endpoint not configured"}',
            media_type="application/json",
            status_code=503,
        )

    hash_input = challenge_code + token + url
    challenge_response = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    logger.info("[eBay] Challenge 검증 요청: challenge_code=%s", challenge_code[:10])

    return Response(
        content=f'{{"challengeResponse": "{challenge_response}"}}',
        media_type="application/json",
    )


@router.post("/ebay/deletion-notification")
async def ebay_deletion_notification(request: Request) -> dict:
    """eBay 마켓플레이스 계정 삭제 알림 수신.

    eBay 구매자가 계정 삭제 시 이 엔드포인트로 POST 요청이 옴.
    해당 구매자의 주문 정보에서 개인정보를 익명화 처리.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    logger.info("[eBay] 계정 삭제 알림 수신: %s", payload)

    # 삭제 대상 유저 정보 추출
    notification = payload.get("notification", {})
    data = notification.get("data", {})
    username = data.get("username", "")
    user_id = data.get("userId", "")

    if username or user_id:
        logger.info("[eBay] 삭제 요청 유저: username=%s, userId=%s", username, user_id)
        # TODO: samba_order 테이블에서 해당 구매자 개인정보 익명화
        # await anonymize_buyer_data(username=username, user_id=user_id)

    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────
# eBay OAuth Authorization Code 콜백 — 신규 판매자계정 연동용 (2026-07-15)
# Developer Portal RuName(redirect)의 auth accepted URL로 지정.
# eBay 로그인+동의 후 ?code=... 로 리다이렉트되면 code→refresh_token 교환해
# 화면에 refresh_token 표시. 그 값을 삼바 마켓계정 additional_fields.oauthToken 에 저장.
#
# App ID/Cert ID 는 새 키셋이라 아직 DB/설정에 없으므로 환경변수로 주입.
#   EBAY_OAUTH_CLIENT_ID  = App ID(Client ID)
#   EBAY_OAUTH_CLIENT_SECRET = Cert ID(Client Secret)
#   EBAY_OAUTH_RUNAME     = RuName (redirect_uri 값으로 사용)
# ─────────────────────────────────────────────────────────────────────────


async def _exchange_oauth_code(code: str) -> dict:
    client_id = settings.ebay_oauth_client_id
    client_secret = settings.ebay_oauth_client_secret
    runame = settings.ebay_oauth_runame
    if not (client_id and client_secret and runame):
        return {"error": "EBAY_OAUTH_* 환경변수 미설정"}
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": runame,
            },
        )
    if resp.status_code != 200:
        return {"error": f"{resp.status_code}: {resp.text[:300]}"}
    return resp.json()


@router.get("/ebay/oauth-accepted")
async def ebay_oauth_accepted(
    code: str = Query("", description="eBay authorization code"),
) -> HTMLResponse:
    """eBay OAuth 동의 성공 콜백 — code→refresh_token 교환 후 화면 표시."""
    if not code:
        return HTMLResponse("<h2>code 파라미터 없음</h2>", status_code=400)
    result = await _exchange_oauth_code(code)
    if result.get("error"):
        logger.error("[eBay OAuth] 토큰 교환 실패: %s", result["error"])
        return HTMLResponse(
            f"<h2>토큰 교환 실패</h2><pre>{result['error']}</pre>", status_code=502
        )
    refresh = result.get("refresh_token", "")
    exp = result.get("refresh_token_expires_in", "")
    logger.info(
        "[eBay OAuth] refresh_token 발급 성공 (만료 %ss) refresh앞=%s",
        exp,
        refresh[:20],
    )
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;padding:2rem'>"
        "<h2>eBay 연동 성공 ✅</h2>"
        f"<p>refresh_token 만료: {exp}초 뒤</p>"
        "<p>아래 refresh_token 값을 담당자에게 전달하세요:</p>"
        f"<textarea style='width:100%;height:120px'>{refresh}</textarea>"
        "</body></html>"
    )


@router.get("/ebay/oauth-declined")
async def ebay_oauth_declined() -> HTMLResponse:
    """eBay OAuth 동의 거부 콜백."""
    return HTMLResponse("<h2>eBay 연동이 취소되었습니다.</h2>", status_code=200)
