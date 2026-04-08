"""SambaWave Contact API router."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.dtos.samba.contact import ContactCreate

router = APIRouter(prefix="/contacts", tags=["samba-contacts"])


def _read_service(session: AsyncSession):
    from backend.domain.samba.contact.repository import SambaContactLogRepository
    from backend.domain.samba.contact.service import SambaContactService

    return SambaContactService(SambaContactLogRepository(session))


def _write_service(session: AsyncSession):
    from backend.domain.samba.contact.repository import SambaContactLogRepository
    from backend.domain.samba.contact.service import SambaContactService

    return SambaContactService(SambaContactLogRepository(session))


@router.get("/stats")
async def get_contact_stats(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    return await svc.get_contact_stats()


@router.get("/templates")
async def get_default_templates():
    from backend.domain.samba.contact.service import SambaContactService

    return SambaContactService.get_default_templates()


@router.get("")
async def list_contacts(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    order_id: Optional[str] = None,
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    return await svc.list_contacts(
        skip=skip, limit=limit, order_id=order_id, status=status
    )


@router.post("", status_code=201)
async def create_contact(
    body: ContactCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    return await svc.send_contact(body.model_dump(exclude_unset=True))


@router.get("/{contact_id}")
async def get_contact(
    contact_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    contact = await svc.get_contact(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="연락 기록을 찾을 수 없습니다")
    return contact


@router.delete("/{contact_id}")
async def delete_contact(
    contact_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    deleted = await svc.delete_contact(contact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="연락 기록을 찾을 수 없습니다")
    return {"ok": True}
