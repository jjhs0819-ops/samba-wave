"""SambaWave Market Account API router."""

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency

router = APIRouter(prefix="/accounts", tags=["samba-accounts"])


def _mask_secret(value: Optional[str]) -> Optional[str]:
    """민감 필드 마스킹 — 앞 4자만 표시."""
    if not value:
        return None
    if len(value) <= 4:
        return "****"
    return value[:4] + "****"


class AccountOut(BaseModel):
    """마켓 계정 응답 DTO — api_key/api_secret 마스킹."""

    id: str
    tenant_id: Optional[str] = None
    market_type: str
    market_name: str
    account_label: str
    seller_id: Optional[str] = None
    business_name: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    additional_fields: Optional[Any] = None
    is_active: bool = True
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime


def _to_account_out(account: Any) -> AccountOut:
    """ORM 모델 → 마스킹된 응답 DTO."""
    return AccountOut(
        id=account.id,
        tenant_id=account.tenant_id,
        market_type=account.market_type,
        market_name=account.market_name,
        account_label=account.account_label,
        seller_id=account.seller_id,
        business_name=account.business_name,
        api_key=_mask_secret(account.api_key),
        api_secret=_mask_secret(account.api_secret),
        additional_fields=account.additional_fields,
        is_active=account.is_active,
        sort_order=account.sort_order,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


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


@router.get("", response_model=list[AccountOut])
async def list_accounts(session: AsyncSession = Depends(get_read_session_dependency)):
    accounts = await _get_service(session).list_accounts()
    return [_to_account_out(a) for a in accounts]


@router.get("/active", response_model=list[AccountOut])
async def list_active_accounts(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    accounts = await _get_service(session).get_active_accounts()
    return [_to_account_out(a) for a in accounts]


@router.get("/markets")
async def get_supported_markets():
    from backend.domain.samba.account.service import SambaAccountService

    return SambaAccountService.SUPPORTED_MARKETS


@router.get("/{account_id}", response_model=AccountOut)
async def get_account(
    account_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    account = await svc.get_account(account_id)
    if not account:
        raise HTTPException(404, "계정을 찾을 수 없습니다")
    return _to_account_out(account)


@router.post("", status_code=201, response_model=AccountOut)
async def create_account(
    body: AccountCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    data = body.model_dump(exclude_unset=True)
    await _enrich_store_slug(data)
    account = await _get_service(session).create_account(data)
    return _to_account_out(account)


class AccountReorderItem(BaseModel):
    id: str
    sort_order: int


@router.put("/reorder")
async def reorder_accounts(
    body: list[AccountReorderItem],
    session: AsyncSession = Depends(get_write_session_dependency),
):
    await _get_service(session).reorder_accounts(
        [{"id": item.id, "sort_order": item.sort_order} for item in body]
    )
    return {"ok": True}


@router.put("/{account_id}")
async def update_account(
    account_id: str,
    body: AccountUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    data = body.model_dump(exclude_unset=True)
    svc = _get_service(session)
    # 기존 계정의 market_type 조회
    existing = await svc.get_account(account_id)
    if not existing:
        raise HTTPException(404, "계정을 찾을 수 없습니다")
    data.setdefault("_market_type", existing.market_type)
    await _enrich_store_slug(data)
    data.pop("_market_type", None)
    result = await svc.update_account(account_id, data)
    if not result:
        raise HTTPException(404, "계정을 찾을 수 없습니다")
    return _to_account_out(result)


async def _enrich_store_slug(data: dict[str, Any]) -> None:
    """스마트스토어 계정이면 API로 스토어 슬러그를 자동 조회하여 additional_fields에 저장."""
    from backend.utils.logger import logger

    market_type = data.get("market_type") or data.get("_market_type", "")
    if market_type != "smartstore":
        return

    extras = data.get("additional_fields") or {}
    if not isinstance(extras, dict):
        return

    client_id = extras.get("clientId", "") or data.get("api_key", "")
    client_secret = extras.get("clientSecret", "") or data.get("api_secret", "")
    if not client_id or not client_secret:
        return

    try:
        from backend.domain.samba.proxy.smartstore import SmartStoreClient

        client = SmartStoreClient(client_id, client_secret)
        info = await client.get_channel_info()
        if info.get("storeSlug"):
            extras["storeSlug"] = info["storeSlug"]
            data["additional_fields"] = extras
            logger.info(f"[계정] 스토어 슬러그 자동 조회: {info['storeSlug']}")
        else:
            # fallback: 등록된 상품에서 슬러그 추출
            logger.info("[계정] 채널 API에서 슬러그 없음 — fallback 시도")
            slug = await client.get_store_slug_fallback()
            if slug:
                extras["storeSlug"] = slug
                data["additional_fields"] = extras
                logger.info(f"[계정] 스토어 슬러그 fallback 성공: {slug}")
            else:
                logger.warning("[계정] 스토어 슬러그 fallback도 실패")
    except Exception as e:
        logger.warning(f"[계정] 스토어 슬러그 조회 실패 (무시): {e}")


@router.put("/{account_id}/toggle", response_model=AccountOut)
async def toggle_account(
    account_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    result = await _get_service(session).toggle_active(account_id)
    if not result:
        raise HTTPException(404, "계정을 찾을 수 없습니다")
    return _to_account_out(result)


@router.delete("/{account_id}")
async def delete_account(
    account_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    if not await _get_service(session).delete_account(account_id):
        raise HTTPException(404, "계정을 찾을 수 없습니다")
    return {"ok": True}
