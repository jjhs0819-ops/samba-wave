"""SourcingRecipe 레포지토리."""

from __future__ import annotations

from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from .model import SourcingRecipe


class SourcingRecipeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_all_versions(self) -> list[dict[str, str]]:
        """활성 레시피 버전 목록만 반환 (site_name, version)."""
        result = await self.session.exec(
            select(SourcingRecipe).where(SourcingRecipe.is_active == True)  # noqa: E712
        )
        return [{"site": r.site_name, "version": r.version} for r in result.all()]

    async def get_by_site(self, site_name: str) -> SourcingRecipe | None:
        """site_name 으로 활성 레시피 단건 조회."""
        result = await self.session.exec(
            select(SourcingRecipe).where(
                SourcingRecipe.site_name == site_name,
                SourcingRecipe.is_active == True,  # noqa: E712
            )
        )
        return result.first()

    async def upsert(
        self, site_name: str, version: str, steps: list[dict[str, Any]]
    ) -> SourcingRecipe:
        """레시피가 있으면 갱신, 없으면 신규 생성."""
        existing = await self.session.exec(
            select(SourcingRecipe).where(SourcingRecipe.site_name == site_name)
        )
        recipe = existing.first()
        if recipe:
            recipe.version = version
            recipe.steps = steps
        else:
            recipe = SourcingRecipe(site_name=site_name, version=version, steps=steps)
        self.session.add(recipe)
        await self.session.commit()
        await self.session.refresh(recipe)
        return recipe
