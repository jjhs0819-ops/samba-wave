from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_write_session_dependency
from backend.domain.samba.license.service import LicenseService
from backend.domain.samba.tenant.middleware import require_admin

router = APIRouter(prefix="/admin/licenses", tags=["license-admin"])


class LicenseCreateRequest(BaseModel):
    buyer_name: str
    buyer_email: str
    expires_at: Optional[datetime] = None
    notes: Optional[str] = None


class LicensePatchRequest(BaseModel):
    is_active: bool


class LicenseResponse(BaseModel):
    id: str
    license_key: str
    buyer_name: str
    buyer_email: str
    is_active: bool
    expires_at: Optional[datetime]
    notes: Optional[str]
    last_verified_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=list[LicenseResponse])
async def list_licenses(
    session: AsyncSession = Depends(get_write_session_dependency),
    _admin_id: str = Depends(require_admin),
) -> list[LicenseResponse]:
    licenses = await LicenseService(session).list_licenses()
    return [LicenseResponse.model_validate(lic.model_dump()) for lic in licenses]


@router.post("", response_model=LicenseResponse)
async def create_license(
    body: LicenseCreateRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
    _admin_id: str = Depends(require_admin),
) -> LicenseResponse:
    expires_at = body.expires_at.replace(tzinfo=None) if body.expires_at else None
    lic = await LicenseService(session).create_license(
        buyer_name=body.buyer_name,
        buyer_email=body.buyer_email,
        expires_at=expires_at,
        notes=body.notes,
    )
    return LicenseResponse.model_validate(lic.model_dump())


@router.patch("/{license_id}", response_model=LicenseResponse)
async def toggle_license(
    license_id: str,
    body: LicensePatchRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
    _admin_id: str = Depends(require_admin),
) -> LicenseResponse:
    lic = await LicenseService(session).toggle_active(license_id, body.is_active)
    if not lic:
        raise HTTPException(status_code=404, detail="라이선스를 찾을 수 없습니다.")
    return LicenseResponse.model_validate(lic.model_dump())


@router.delete("/{license_id}")
async def delete_license(
    license_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
    _admin_id: str = Depends(require_admin),
) -> dict:
    deleted = await LicenseService(session).delete_license(license_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="라이선스를 찾을 수 없습니다.")
    return {"message": "삭제되었습니다."}
