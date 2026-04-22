from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_write_session_dependency
from backend.domain.samba.license.service import LicenseService

router = APIRouter(tags=["license"])


class LicenseVerifyRequest(BaseModel):
    license_key: str


class LicenseVerifyResponse(BaseModel):
    valid: bool
    message: str
    expires_at: str | None = None
    buyer_name: str | None = None


@router.post("/license/verify", response_model=LicenseVerifyResponse)
async def verify_license(
    body: LicenseVerifyRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> LicenseVerifyResponse:
    result = await LicenseService(session).verify(body.license_key)
    return LicenseVerifyResponse(**result)
