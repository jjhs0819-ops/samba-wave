"""네이버 톡톡 웹훅 수신 + 메시지 발송 라우터."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_write_session_dependency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/talktalk", tags=["samba-talktalk"])

TALKTALK_SEND_URL = "https://gw.talk.naver.com/chatbot/v1/event"


async def _get_talktalk_api_key(session: AsyncSession) -> str:
    """톡톡 API KEY 조회."""
    from sqlmodel import select
    from backend.domain.samba.forbidden.model import SambaSettings
    result = await session.execute(
        select(SambaSettings).where(SambaSettings.key == "talktalk_api_key")
    )
    row = result.scalar_one_or_none()
    return (row.value if row and row.value else "") or ""


@router.post("/webhook")
async def talktalk_webhook(
    request: Request,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """톡톡 웹훅 수신 — 고객 메시지 도착 시 CS 테이블에 자동 저장.

    톡톡 파트너센터에서 이 URL을 웹훅으로 등록:
    https://{도메인}/api/v1/samba/talktalk/webhook
    """
    try:
        body = await request.json()
    except Exception:
        return {"success": True}  # 톡톡은 200 응답 필수

    event = body.get("event", "")
    user_id = body.get("user", "")

    logger.info(f"[톡톡] 웹훅 수신: event={event}, user={user_id}")

    # send 이벤트만 처리 (고객이 메시지를 보냈을 때)
    if event == "send":
        text_content = body.get("textContent", {})
        message = text_content.get("text", "")

        if not message:
            # 이미지 등 텍스트 아닌 메시지
            image_content = body.get("imageContent", {})
            if image_content:
                message = f"[이미지] {image_content.get('imageUrl', '')}"

        if message:
            from backend.domain.samba.cs_inquiry.repository import SambaCSInquiryRepository
            from backend.domain.samba.cs_inquiry.service import SambaCSInquiryService

            svc = SambaCSInquiryService(SambaCSInquiryRepository(session))

            inquiry_data = {
                "market": "스마트스토어",
                "market_inquiry_no": f"talktalk_{user_id}_{int(datetime.now(timezone.utc).timestamp())}",
                "account_name": "톡톡",
                "inquiry_type": "talktalk",
                "questioner": user_id,
                "product_name": "",
                "content": message,
                "reply_status": "pending",
                "inquiry_date": datetime.now(timezone.utc),
            }

            await svc.create_inquiry(inquiry_data)
            logger.info(f"[톡톡] CS 문의 저장: user={user_id}, msg={message[:50]}")

    # open 이벤트 (사용자가 채팅창 진입)
    elif event == "open":
        logger.info(f"[톡톡] 사용자 입장: {user_id}")

    # 톡톡은 반드시 200 응답해야 함
    return {"success": True}


class TalkTalkSendRequest(BaseModel):
    user: str  # 톡톡 사용자 ID
    text: str  # 보낼 메시지


@router.post("/send")
async def send_talktalk_message(
    body: TalkTalkSendRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """톡톡으로 메시지 발송 (CS 답변 전송용)."""
    api_key = await _get_talktalk_api_key(session)
    if not api_key:
        raise HTTPException(400, "톡톡 API KEY가 설정되지 않았습니다. 설정 > 스마트스토어에서 등록해주세요.")

    payload = {
        "event": "send",
        "user": body.user,
        "textContent": {
            "text": body.text,
        },
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            TALKTALK_SEND_URL,
            json=payload,
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "Authorization": api_key,
            },
        )

    result = resp.json() if resp.is_success else {"error": resp.text}
    logger.info(f"[톡톡] 발송 결과: {resp.status_code} → {result}")

    if not resp.is_success:
        raise HTTPException(502, f"톡톡 메시지 발송 실패: {resp.status_code}")

    return {"success": True, "message": "톡톡 메시지 발송 완료", "data": result}
