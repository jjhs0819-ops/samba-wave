"""SambaWave Channel API router."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.channel.model import SambaChannel
from backend.domain.samba.channel.repository import SambaChannelRepository
from backend.domain.samba.channel.service import SambaChannelService
from backend.dtos.samba.channel import ChannelCreate, ChannelUpdate

router = APIRouter(prefix="/channels", tags=["samba-channels"])


def _read_service(session: AsyncSession) -> SambaChannelService:
    return SambaChannelService(SambaChannelRepository(session))


def _write_service(session: AsyncSession) -> SambaChannelService:
    return SambaChannelService(SambaChannelRepository(session))


@router.get("", response_model=list[SambaChannel])
async def list_channels(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    return await svc.list_channels(skip=skip, limit=limit)


@router.get("/{channel_id}", response_model=SambaChannel)
async def get_channel(
    channel_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    channel = await svc.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="판매처를 찾을 수 없습니다")
    return channel


@router.post("", response_model=SambaChannel, status_code=201)
async def create_channel(
    body: ChannelCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    return await svc.create_channel(body.model_dump(exclude_unset=True))


@router.put("/{channel_id}", response_model=SambaChannel)
async def update_channel(
    channel_id: str,
    body: ChannelUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    channel = await svc.update_channel(channel_id, body.model_dump(exclude_unset=True))
    if not channel:
        raise HTTPException(status_code=404, detail="판매처를 찾을 수 없습니다")
    return channel


@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    deleted = await svc.delete_channel(channel_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="판매처를 찾을 수 없습니다")
    return {"ok": True}
