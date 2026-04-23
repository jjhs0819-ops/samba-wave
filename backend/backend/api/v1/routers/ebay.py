"""eBay Marketplace Account Deletion Notification 엔드포인트."""

import hashlib
import logging

from fastapi import APIRouter, Query, Request, Response

logger = logging.getLogger(__name__)

# eBay Developer Portal에 등록한 Verification Token과 동일하게 설정
VERIFICATION_TOKEN = "sambaWaveEbayVerificationToken2026"
ENDPOINT_URL = (
    "https://samba-wave-api-vpob3wc2na-du.a.run.app/api/v1/ebay/deletion-notification"
)

router = APIRouter(tags=["ebay"])


@router.get("/ebay/deletion-notification")
async def ebay_deletion_challenge(
    challenge_code: str = Query(..., description="eBay challenge code"),
) -> Response:
    """eBay endpoint 검증 — challenge-response 응답.

    eBay가 엔드포인트 등록 시 GET 요청으로 challenge_code를 보내면
    SHA-256(challenge_code + verification_token + endpoint_url) 해시를 반환.
    """
    hash_input = challenge_code + VERIFICATION_TOKEN + ENDPOINT_URL
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
