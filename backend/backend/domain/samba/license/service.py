from datetime import datetime
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.license.model import SambaLicense, generate_license_key
from backend.domain.samba.license.repository import LicenseRepository


class LicenseService:
    def __init__(self, session: AsyncSession):
        self.repo = LicenseRepository(session)

    async def verify(self, license_key: str) -> dict:
        """라이선스 키 검증 — public 엔드포인트용."""
        lic = await self.repo.get_by_key(license_key)
        if not lic:
            return {"valid": False, "message": "등록되지 않은 라이선스 키입니다."}
        if not lic.is_active:
            return {"valid": False, "message": "비활성화된 라이선스입니다."}
        if lic.expires_at and lic.expires_at < datetime.utcnow():
            return {
                "valid": False,
                "message": "만료된 라이선스입니다.",
                "expires_at": lic.expires_at.isoformat(),
            }
        lic.last_verified_at = datetime.utcnow()
        await self.repo.update(lic)
        return {
            "valid": True,
            "message": "유효한 라이선스입니다.",
            "expires_at": lic.expires_at.isoformat() if lic.expires_at else None,
            "buyer_name": lic.buyer_name,
        }

    async def create_license(
        self,
        buyer_name: str,
        buyer_email: str,
        expires_at: Optional[datetime] = None,
        notes: Optional[str] = None,
    ) -> SambaLicense:
        key = generate_license_key()
        lic = SambaLicense(
            license_key=key,
            buyer_name=buyer_name,
            buyer_email=buyer_email,
            expires_at=expires_at,
            notes=notes,
        )
        return await self.repo.create(lic)

    async def list_licenses(self) -> list[SambaLicense]:
        return await self.repo.list_all()

    async def toggle_active(
        self, license_id: str, is_active: bool
    ) -> Optional[SambaLicense]:
        lic = await self.repo.get_by_id(license_id)
        if not lic:
            return None
        lic.is_active = is_active
        return await self.repo.update(lic)

    async def delete_license(self, license_id: str) -> bool:
        lic = await self.repo.get_by_id(license_id)
        if not lic:
            return False
        await self.repo.delete(lic)
        return True
