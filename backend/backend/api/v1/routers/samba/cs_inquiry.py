"""SambaWave CS 문의 API router."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.dtos.samba.cs_inquiry import (
    CSInquiryBatchDelete,
    CSInquiryCreate,
    CSInquiryReply,
)

router = APIRouter(prefix="/cs-inquiries", tags=["samba-cs-inquiries"])


def _read_service(session: AsyncSession):
    from backend.domain.samba.cs_inquiry.repository import SambaCSInquiryRepository
    from backend.domain.samba.cs_inquiry.service import SambaCSInquiryService

    return SambaCSInquiryService(SambaCSInquiryRepository(session))


def _write_service(session: AsyncSession):
    from backend.domain.samba.cs_inquiry.repository import SambaCSInquiryRepository
    from backend.domain.samba.cs_inquiry.service import SambaCSInquiryService

    return SambaCSInquiryService(SambaCSInquiryRepository(session))


@router.get("/stats")
async def get_cs_stats(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """CS 문의 통계."""
    svc = _read_service(session)
    return await svc.get_stats()


@router.get("/templates")
async def get_reply_templates():
    """CS 답변 템플릿 목록."""
    from backend.domain.samba.cs_inquiry.service import SambaCSInquiryService

    return SambaCSInquiryService.get_reply_templates()


@router.get("")
async def list_cs_inquiries(
    skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=200),
    market: Optional[str] = None,
    inquiry_type: Optional[str] = None,
    reply_status: Optional[str] = None,
    search: Optional[str] = None,
    sort_field: str = Query("inquiry_date"),
    sort_desc: bool = Query(True),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """CS 문의 목록 (필터 + 페이지네이션)."""
    svc = _read_service(session)
    return await svc.list_inquiries(
        skip=skip,
        limit=limit,
        market=market,
        inquiry_type=inquiry_type,
        reply_status=reply_status,
        search=search,
        sort_field=sort_field,
        sort_desc=sort_desc,
    )


@router.post("", status_code=201)
async def create_cs_inquiry(
    body: CSInquiryCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """CS 문의 수동 등록."""
    svc = _write_service(session)
    return await svc.create_inquiry(body.model_dump(exclude_unset=True))


@router.get("/{inquiry_id}")
async def get_cs_inquiry(
    inquiry_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """CS 문의 단건 조회."""
    svc = _read_service(session)
    inquiry = await svc.get_inquiry(inquiry_id)
    if not inquiry:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다")
    return inquiry


@router.post("/{inquiry_id}/reply")
async def reply_cs_inquiry(
    inquiry_id: str,
    body: CSInquiryReply,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """CS 문의 답변 등록."""
    svc = _write_service(session)
    updated = await svc.reply_inquiry(inquiry_id, body.reply)
    if not updated:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다")
    return updated


@router.post("/sync-from-markets")
async def sync_cs_from_markets(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """마켓에서 CS 문의 동기화 (스마트스토어 고객문의 + 톡톡)."""
    import logging
    from datetime import datetime, timedelta, timezone
    from sqlmodel import select
    from backend.domain.samba.forbidden.model import SambaSettings
    from backend.domain.samba.proxy.smartstore import SmartStoreClient
    from backend.domain.samba.cs_inquiry.model import SambaCSInquiry

    logger = logging.getLogger(__name__)
    svc = _write_service(session)
    synced = 0
    errors = []

    # 스마트스토어 계정 조회
    try:
        settings_result = await session.execute(
            select(SambaSettings).where(SambaSettings.key.like("store_smartstore%"))
        )
        ss_settings = settings_result.scalars().all()
    except Exception as e:
        raise HTTPException(500, f"설정 조회 실패: {e}")

    for setting in ss_settings:
        try:
            import json
            config = json.loads(setting.value) if isinstance(setting.value, str) else setting.value
            client_id = config.get("clientId", "")
            client_secret = config.get("clientSecret", "")
            account_name = config.get("businessName", "") or config.get("storeId", "")

            if not client_id or not client_secret:
                continue

            client = SmartStoreClient(client_id, client_secret)

            # 최근 30일 문의 조회 (KST 기준 ISO 8601)
            from zoneinfo import ZoneInfo
            kst = ZoneInfo("Asia/Seoul")
            now_kst = datetime.now(kst)
            # 종료일은 내일 자정 (당일 문의 포함)
            end_date = (now_kst + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000+09:00")
            start_date = (now_kst - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00.000+09:00")

            result = await client.get_inquiries(
                from_date=start_date,
                to_date=end_date,
                size=100,
            )

            # 응답 구조 디버깅
            logger.info(f"[CS동기화] API 응답 키: {list(result.keys()) if isinstance(result, dict) else type(result)}")
            data = result.get("data", result)
            if isinstance(data, dict):
                logger.info(f"[CS동기화] data 키: {list(data.keys())}")

            # 다양한 응답 구조 대응
            contents = []
            if isinstance(data, dict):
                contents = data.get("contents", [])
                if not contents:
                    contents = data.get("content", [])
                if not contents:
                    # 응답 자체가 페이지네이션 래핑된 경우
                    for key in data:
                        val = data[key]
                        if isinstance(val, list) and val:
                            contents = val
                            logger.info(f"[CS동기화] '{key}' 키에서 {len(val)}건 발견")
                            break
            elif isinstance(data, list):
                contents = data

            for item in contents:
                inquiry_no = str(item.get("questionId", item.get("inquiryNo", item.get("id", ""))))
                if not inquiry_no:
                    continue

                # 중복 체크
                existing = await session.execute(
                    select(SambaCSInquiry).where(
                        SambaCSInquiry.market == "스마트스토어",
                        SambaCSInquiry.market_inquiry_no == inquiry_no,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                # 문의 유형: 상품 Q&A
                inquiry_type = "product_question"

                # 답변 여부 (API 응답 필드: answered, answer)
                is_answered = item.get("answered", False)
                reply_content = item.get("answer", "")

                inquiry_data = {
                    "market": "스마트스토어",
                    "market_inquiry_no": inquiry_no,
                    "market_answer_no": None,
                    "market_order_id": None,
                    "account_name": account_name,
                    "inquiry_type": inquiry_type,
                    "questioner": item.get("maskedWriterId", ""),
                    "product_name": item.get("productName", ""),
                    "product_image": "",
                    "content": item.get("question", ""),
                    "reply": reply_content if is_answered else None,
                    "reply_status": "replied" if is_answered else "pending",
                    "inquiry_date": item.get("createDate", None),
                    "replied_at": None,
                }

                await svc.create_inquiry(inquiry_data)
                synced += 1

            logger.info(f"[CS동기화] 스마트스토어({account_name}): {len(contents)}건 조회, {synced}건 동기화")

        except Exception as e:
            logger.error(f"[CS동기화] 스마트스토어 동기화 실패: {e}")
            errors.append(str(e))

    return {
        "success": True,
        "synced": synced,
        "errors": errors,
        "message": f"CS 문의 {synced}건 동기화 완료" + (f" (에러 {len(errors)}건)" if errors else ""),
    }


@router.post("/{inquiry_id}/send-reply")
async def send_reply_to_market(
    inquiry_id: str,
    body: CSInquiryReply,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """CS 문의 답변을 마켓에 전송."""
    import json
    from datetime import datetime, timezone
    from sqlmodel import select
    from backend.domain.samba.forbidden.model import SambaSettings
    from backend.domain.samba.proxy.smartstore import SmartStoreClient

    svc = _write_service(session)
    inquiry = await svc.get_inquiry(inquiry_id)
    if not inquiry:
        raise HTTPException(404, "문의를 찾을 수 없습니다")

    if not inquiry.market_inquiry_no:
        raise HTTPException(400, "마켓 문의 번호가 없습니다 (수동 등록 문의는 마켓 전송 불가)")

    if inquiry.market == "스마트스토어":
        # 스마트스토어 계정 조회
        settings_result = await session.execute(
            select(SambaSettings).where(SambaSettings.key.like("store_smartstore%"))
        )
        ss_settings = settings_result.scalars().first()
        if not ss_settings:
            raise HTTPException(400, "스마트스토어 계정 설정이 없습니다")

        config = json.loads(ss_settings.value) if isinstance(ss_settings.value, str) else ss_settings.value
        client = SmartStoreClient(config["clientId"], config["clientSecret"])

        inquiry_no = int(inquiry.market_inquiry_no)

        if inquiry.market_answer_no:
            # 기존 답변 수정
            result = await client.update_inquiry_answer(
                inquiry_no, int(inquiry.market_answer_no), body.reply,
            )
        else:
            # 새 답변 등록
            result = await client.answer_inquiry(inquiry_no, body.reply)

        # 답변 번호 저장
        answer_data = result.get("data", {})
        answer_no = str(answer_data.get("inquiryCommentNo", ""))

        from backend.domain.samba.cs_inquiry.repository import SambaCSInquiryRepository
        repo = SambaCSInquiryRepository(session)
        await repo.update_async(
            inquiry_id,
            reply=body.reply,
            reply_status="replied",
            market_answer_no=answer_no if answer_no else inquiry.market_answer_no,
            replied_at=datetime.now(timezone.utc),
        )

        return {"success": True, "message": "스마트스토어에 답변 전송 완료", "data": result.get("data")}

    # 톡톡 문의는 톡톡 API로 답변
    if inquiry.inquiry_type == "talktalk" and inquiry.questioner:
        api_key = ""
        try:
            result = await session.execute(
                select(SambaSettings).where(SambaSettings.key == "talktalk_api_key")
            )
            row = result.scalar_one_or_none()
            api_key = (row.value if row and row.value else "") or ""
        except Exception:
            pass

        if not api_key:
            raise HTTPException(400, "톡톡 API KEY가 설정되지 않았습니다")

        import httpx
        payload = {
            "event": "send",
            "user": inquiry.questioner,
            "textContent": {"text": body.reply},
        }
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            resp = await http_client.post(
                "https://gw.talk.naver.com/chatbot/v1/event",
                json=payload,
                headers={"Content-Type": "application/json;charset=UTF-8", "Authorization": api_key},
            )

        if not resp.is_success:
            raise HTTPException(502, f"톡톡 답변 발송 실패: {resp.status_code}")

        # DB 업데이트
        from backend.domain.samba.cs_inquiry.repository import SambaCSInquiryRepository
        repo = SambaCSInquiryRepository(session)
        await repo.update_async(
            inquiry_id,
            reply=body.reply,
            reply_status="replied",
            replied_at=datetime.now(timezone.utc),
        )

        return {"success": True, "message": "톡톡으로 답변 발송 완료"}

    raise HTTPException(400, f"'{inquiry.market}' 마켓은 아직 답변 전송을 지원하지 않습니다")


@router.post("/batch-delete")
async def batch_delete_cs_inquiries(
    body: CSInquiryBatchDelete,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """CS 문의 선택 삭제."""
    svc = _write_service(session)
    count = await svc.delete_batch(body.ids)
    return {"deleted": count}


@router.delete("/{inquiry_id}")
async def delete_cs_inquiry(
    inquiry_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """CS 문의 단건 삭제."""
    svc = _write_service(session)
    deleted = await svc.delete_inquiry(inquiry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다")
    return {"ok": True}
