"""SambaWave Forbidden Word API router."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency

router = APIRouter(prefix="/forbidden", tags=["samba-forbidden"])


class WordCreate(BaseModel):
    word: str
    type: str = "forbidden"  # forbidden | deletion
    scope: str = "title"  # title | description | both
    group_id: Optional[str] = None
    is_active: bool = True


class WordUpdate(BaseModel):
    word: Optional[str] = None
    type: Optional[str] = None
    scope: Optional[str] = None
    is_active: Optional[bool] = None


class ValidateRequest(BaseModel):
    name: str


def _get_service(session: AsyncSession):
    from backend.domain.samba.forbidden.repository import (
        SambaForbiddenWordRepository,
        SambaSettingsRepository,
    )
    from backend.domain.samba.forbidden.service import SambaForbiddenService

    return SambaForbiddenService(
        SambaForbiddenWordRepository(session),
        SambaSettingsRepository(session),
    )


@router.get("/words")
async def list_words(
    type: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    if type:
        return await svc.list_by_type(type)
    return await svc.list_words()


@router.post("/words", status_code=201)
async def create_word(
    body: WordCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    return await _get_service(session).create_word(body.model_dump(exclude_unset=True))


@router.put("/words/{word_id}")
async def update_word(
    word_id: str,
    body: WordUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    result = await _get_service(session).update_word(word_id, body.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(404, "단어를 찾을 수 없습니다")
    return result


@router.put("/words/{word_id}/toggle")
async def toggle_word(
    word_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    result = await _get_service(session).toggle_word(word_id)
    if not result:
        raise HTTPException(404, "단어를 찾을 수 없습니다")
    return result


@router.delete("/words/{word_id}")
async def delete_word(
    word_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    if not await _get_service(session).delete_word(word_id):
        raise HTTPException(404, "단어를 찾을 수 없습니다")
    return {"ok": True}


@router.post("/validate")
async def validate_product_name(
    body: ValidateRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    return await svc.validate_product({"name": body.name})


@router.post("/clean")
async def clean_product_name(
    body: ValidateRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    return {"clean_name": await svc.clean_product_name(body.name)}


# ── Settings (generic key-value store) ──

@router.get("/settings/{key}")
async def get_setting(
    key: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    return await svc.get_setting(key)


@router.put("/settings/{key}")
async def save_setting(
    key: str,
    body: dict,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_service(session)
    return await svc.save_setting(key, body.get("value"))
