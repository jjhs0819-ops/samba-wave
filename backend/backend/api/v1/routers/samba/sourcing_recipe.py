"""소싱처 수집 레시피 API — GET은 확장앱(X-Api-Key), PUT은 관리자(JWT)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.sourcing_recipe.repository import SourcingRecipeRepository

# JWT 면제 라우터 (확장앱 X-Api-Key만으로 호출)
extension_router = APIRouter(prefix="/sourcing-recipes", tags=["sourcing-recipe"])
# JWT 필요 라우터 (관리자 수정용, app_factory에서 samba_auth 주입)
router = APIRouter(prefix="/sourcing-recipes", tags=["sourcing-recipe"])


class RecipeUpsertRequest(BaseModel):
    version: str
    steps: list[dict[str, Any]]


@extension_router.get("")
async def list_recipe_versions(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """활성 레시피 버전 목록 반환 (확장앱 캐시 비교용)."""
    repo = SourcingRecipeRepository(session)
    recipes = await repo.get_all_versions()
    return {"recipes": recipes}


@extension_router.get("/{site}")
async def get_recipe(
    site: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """특정 소싱처 레시피 풀 내용 반환."""
    repo = SourcingRecipeRepository(session)
    recipe = await repo.get_by_site(site)
    if not recipe:
        raise HTTPException(status_code=404, detail=f"레시피 없음: {site}")
    return {"site": recipe.site_name, "version": recipe.version, "steps": recipe.steps}


@router.put("/{site}")
async def upsert_recipe(
    site: str,
    body: RecipeUpsertRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """레시피 추가/수정 (관리자 전용)."""
    repo = SourcingRecipeRepository(session)
    recipe = await repo.upsert(site, body.version, body.steps)
    return {"site": recipe.site_name, "version": recipe.version}
