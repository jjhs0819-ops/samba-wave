"""SambaWave Category API router."""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency

router = APIRouter(prefix="/categories", tags=["samba-categories"])


class MappingCreate(BaseModel):
    source_site: str
    source_category: str
    target_mappings: Optional[Any] = None
    applied_policy_id: Optional[str] = None


class MappingUpdate(BaseModel):
    target_mappings: Optional[Any] = None
    applied_policy_id: Optional[str] = None


class TreeSave(BaseModel):
    cat1: Optional[list] = None
    cat2: Optional[Any] = None
    cat3: Optional[Any] = None
    cat4: Optional[Any] = None


def _get_service(session: AsyncSession):
    from backend.domain.samba.category.repository import (
        SambaCategoryMappingRepository,
        SambaCategoryTreeRepository,
    )
    from backend.domain.samba.category.service import SambaCategoryService

    return SambaCategoryService(
        SambaCategoryMappingRepository(session),
        SambaCategoryTreeRepository(session),
    )


# ── Mappings ──

@router.get("/mappings")
async def list_mappings(session: AsyncSession = Depends(get_read_session_dependency)):
    return await _get_service(session).list_mappings()


@router.post("/mappings", status_code=201)
async def create_mapping(
    body: MappingCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    return await _get_service(session).create_mapping(body.model_dump(exclude_unset=True))


@router.put("/mappings/{mapping_id}")
async def update_mapping(
    mapping_id: str,
    body: MappingUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    result = await _get_service(session).update_mapping(mapping_id, body.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(404, "매핑을 찾을 수 없습니다")
    return result


@router.delete("/mappings/{mapping_id}")
async def delete_mapping(
    mapping_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    if not await _get_service(session).delete_mapping(mapping_id):
        raise HTTPException(404, "매핑을 찾을 수 없습니다")
    return {"ok": True}


@router.get("/mappings/find")
async def find_mapping(
    source_site: str = Query(...),
    source_category: str = Query(...),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    return await _get_service(session).find_mapping(source_site, source_category)


@router.get("/suggest")
async def suggest_category(
    source_category: str = Query(...),
    target_market: str = Query(...),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    return _get_service(session).suggest_category(source_category, target_market)


# ── Category Tree ──

@router.get("/tree/{site_name}")
async def get_tree(
    site_name: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    return await _get_service(session).get_category_tree(site_name)


@router.put("/tree/{site_name}")
async def save_tree(
    site_name: str,
    body: TreeSave,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    return await _get_service(session).save_category_tree(site_name, body.model_dump())


@router.delete("/tree/{site_name}")
async def delete_tree(
    site_name: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    await _get_service(session).delete_category_tree(site_name)
    return {"ok": True}
