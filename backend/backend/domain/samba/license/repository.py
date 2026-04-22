from datetime import datetime
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.license.model import SambaLicense


class LicenseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_key(self, license_key: str) -> Optional[SambaLicense]:
        result = await self.session.exec(
            select(SambaLicense).where(SambaLicense.license_key == license_key)
        )
        return result.first()

    async def get_by_id(self, license_id: str) -> Optional[SambaLicense]:
        result = await self.session.exec(
            select(SambaLicense).where(SambaLicense.id == license_id)
        )
        return result.first()

    async def list_all(self) -> list[SambaLicense]:
        result = await self.session.exec(
            select(SambaLicense).order_by(SambaLicense.created_at.desc())
        )
        return list(result.all())

    async def create(self, license: SambaLicense) -> SambaLicense:
        self.session.add(license)
        await self.session.commit()
        await self.session.refresh(license)
        return license

    async def update(self, license: SambaLicense) -> SambaLicense:
        license.updated_at = datetime.utcnow()
        self.session.add(license)
        await self.session.commit()
        await self.session.refresh(license)
        return license

    async def delete(self, license: SambaLicense) -> None:
        await self.session.delete(license)
        await self.session.commit()
