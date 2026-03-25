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
