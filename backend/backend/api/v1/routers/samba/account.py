"""SambaWave Market Account API router."""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency

router = APIRouter(prefix="/accounts", tags=["samba-accounts"])


class AccountCreate(BaseModel):
    market_type: str
    seller_id: Optional[str] = None
    business_name: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    additional_fields: Optional[Any] = None
    is_active: bool = True


class AccountUpdate(BaseModel):
    account_label: Optional[str] = None
    seller_id: Optional[str] = None
    business_name: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    additional_fields: Optional[Any] = None
    is_active: Optional[bool] = None


def _get_service(session: AsyncSession):
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.account.service import SambaAccountService

    return SambaAccountService(SambaMarketAccountRepository(session))


@router.get("")
async def list_accounts(session: AsyncSession = Depends(get_read_session_dependency)):
    return await _get_service(session).list_accounts()


@router.get("/active")
async def list_active_accounts(session: AsyncSession = Depends(get_read_session_dependency)):
    return await _get_service(session).get_active_accounts()


@router.get("/markets")
async def get_supported_markets():
    from backend.domain.samba.account.service import SambaAccountService
    return SambaAccountService.SUPPORTED_MARKETS


@router.get("/{account_id}")
async def get_account(
    account_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    account = await svc.get_account(account_id)
    if not account:
        raise HTTPException(404, "계정을 찾을 수 없습니다")
    return account


@router.post("", status_code=201)
async def create_account(
    body: AccountCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    return await _get_service(session).create_account(body.model_dump(exclude_unset=True))


@router.put("/{account_id}")
async def update_account(
    account_id: str,
    body: AccountUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    result = await _get_service(session).update_account(account_id, body.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(404, "계정을 찾을 수 없습니다")
    return result


@router.put("/{account_id}/toggle")
async def toggle_account(
    account_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    result = await _get_service(session).toggle_active(account_id)
    if not result:
        raise HTTPException(404, "계정을 찾을 수 없습니다")
    return result


@router.delete("/{account_id}")
async def delete_account(
    account_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    if not await _get_service(session).delete_account(account_id):
        raise HTTPException(404, "계정을 찾을 수 없습니다")
    return {"ok": True}
