"""소싱처 계정 API 라우터."""

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from sqlmodel import select

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.tenant.middleware import get_optional_tenant_id
from backend.dtos.samba.sourcing_account import (
    SourcingAccountCreate,
    SourcingAccountUpdate,
)
from backend.utils.logger import logger

router = APIRouter(prefix="/sourcing-accounts", tags=["samba-sourcing-accounts"])


def _read_service(session: AsyncSession):
    from backend.domain.samba.sourcing_account.repository import (
        SambaSourcingAccountRepository,
    )
    from backend.domain.samba.sourcing_account.service import (
        SambaSourcingAccountService,
    )

    return SambaSourcingAccountService(SambaSourcingAccountRepository(session))


def _write_service(session: AsyncSession):
    from backend.domain.samba.sourcing_account.repository import (
        SambaSourcingAccountRepository,
    )
    from backend.domain.samba.sourcing_account.service import (
        SambaSourcingAccountService,
    )

    return SambaSourcingAccountService(SambaSourcingAccountRepository(session))


@router.get("")
async def list_sourcing_accounts(
    site_name: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    from backend.domain.samba.sourcing_account.model import SambaSourcingAccount

    # tenant_id가 있으면 해당 테넌트 소싱처 계정만 조회
    if tenant_id is not None:
        stmt = select(SambaSourcingAccount).order_by(
            SambaSourcingAccount.created_at.desc()
        )
        stmt = stmt.where(SambaSourcingAccount.tenant_id == tenant_id)
        if site_name:
            stmt = stmt.where(SambaSourcingAccount.site_name == site_name)
        result = await session.execute(stmt)
        return result.scalars().all()
    return await _read_service(session).list_accounts(site_name=site_name)


@router.get("/sites")
async def get_supported_sites():
    from backend.domain.samba.sourcing_account.service import (
        SambaSourcingAccountService,
    )

    return SambaSourcingAccountService.get_supported_sites()


@router.get("/chrome-profiles")
async def get_chrome_profiles():
    """PC에 존재하는 크롬 프로필 목록 반환."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    local_state_path = (
        Path(local_app_data) / "Google" / "Chrome" / "User Data" / "Local State"
    )
    if not local_state_path.exists():
        return []
    try:
        data = json.loads(local_state_path.read_text(encoding="utf-8"))
        profiles_info = data.get("profile", {}).get("info_cache", {})
        results = []
        for directory, info in profiles_info.items():
            results.append(
                {
                    "directory": directory,
                    "name": info.get("name", directory),
                    "gaia_name": info.get("gaia_name", ""),
                }
            )
        return sorted(results, key=lambda x: x["directory"])
    except Exception as e:
        logger.warning(f"크롬 프로필 목록 조회 실패: {e}")
        return []


# 잔액 체크 요청 플래그 (확장앱이 폴링으로 확인)
_balance_check_requested = False


@router.post("/request-balance-check")
async def request_balance_check():
    """프론트에서 잔액 체크 요청 → 확장앱이 폴링으로 확인 후 실행."""
    global _balance_check_requested
    _balance_check_requested = True
    return {"ok": True}


@router.get("/balance-check-requested")
async def get_balance_check_requested():
    """확장앱이 폴링으로 확인하는 잔액 체크 요청 플래그."""
    global _balance_check_requested
    if _balance_check_requested:
        _balance_check_requested = False
        return {"requested": True}
    return {"requested": False}


@router.get("/{account_id}")
async def get_sourcing_account(
    account_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    account = await svc.get_account(account_id)
    if not account:
        raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
    return account


@router.post("", status_code=201)
async def create_sourcing_account(
    body: SourcingAccountCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    data = body.model_dump(exclude_unset=True)
    # tenant_id가 있으면 신규 소싱처 계정에 테넌트 정보 설정
    if tenant_id is not None:
        data["tenant_id"] = tenant_id
    return await _write_service(session).create_account(data)


@router.put("/{account_id}")
async def update_sourcing_account(
    account_id: str,
    body: SourcingAccountUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    svc = _write_service(session)
    # tenant_id가 있으면 소유권 검증
    if tenant_id is not None:
        existing = await svc.get_account(account_id)
        if not existing:
            raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
        if existing.tenant_id != tenant_id:
            raise HTTPException(403, "해당 계정에 대한 권한이 없습니다")
    result = await svc.update_account(account_id, body.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
    return result


@router.put("/{account_id}/toggle")
async def toggle_sourcing_account(
    account_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    svc = _write_service(session)
    # tenant_id가 있으면 소유권 검증
    if tenant_id is not None:
        existing = await svc.get_account(account_id)
        if not existing:
            raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
        if existing.tenant_id != tenant_id:
            raise HTTPException(403, "해당 계정에 대한 권한이 없습니다")
    result = await svc.toggle_active(account_id)
    if not result:
        raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
    return result


@router.delete("/{account_id}")
async def delete_sourcing_account(
    account_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    svc = _write_service(session)
    # tenant_id가 있으면 소유권 검증
    if tenant_id is not None:
        existing = await svc.get_account(account_id)
        if not existing:
            raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
        if existing.tenant_id != tenant_id:
            raise HTTPException(403, "해당 계정에 대한 권한이 없습니다")
    if not await svc.delete_account(account_id):
        raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
    return {"ok": True}


class SyncMembershipRequest(BaseModel):
    site_name: str
    membership_rate: float
    membership_grade: str = ""


@router.post("/sync-membership")
async def sync_membership_from_extension(
    body: SyncMembershipRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """확장앱에서 멤버십 등급 수신 → 소싱처 계정에 저장 + 캐시 갱신."""
    from backend.domain.samba.proxy.abcmart import ARTSourcingClient

    svc = _write_service(session)
    accounts = await svc.list_accounts(site_name=body.site_name)

    for account in accounts:
        extra = dict(account.additional_fields or {})
        extra["membership_rate"] = body.membership_rate
        extra["membership_grade"] = body.membership_grade
        await svc.repo.update_async(account.id, additional_fields=extra)

    # 인메모리 캐시 갱신
    ARTSourcingClient.set_membership_rate(body.membership_rate)

    logger.info(
        f"[멤버십동기화] {body.site_name}: {body.membership_grade} ({body.membership_rate}%)"
    )
    return {
        "ok": True,
        "rate": body.membership_rate,
        "grade": body.membership_grade,
    }


class SyncBalanceRequest(BaseModel):
    money: float = 0
    mileage: float = 0
    profileEmail: Optional[str] = None
    username: Optional[str] = None
    cookie: Optional[str] = None
    expired: bool = False


@router.post("/sync-balance")
async def sync_balance_from_extension(
    body: SyncBalanceRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """확장앱에서 잔액 수신 → 크롬 프로필 Gmail로 계정 매칭 → 저장."""
    svc = _write_service(session)
    accounts = await svc.list_accounts(site_name="MUSINSA")
    matched = None

    # 1순위: 크롬 프로필 Gmail(memo 필드)로 매칭
    if body.profileEmail:
        matched = next(
            (
                a
                for a in accounts
                if a.memo and a.memo.lower() == body.profileEmail.lower()
            ),
            None,
        )

    # 2순위: 쿠키 문자열에 아이디가 포함되어 있는지 확인
    if not matched and body.cookie:
        for a in accounts:
            if a.username and a.username in body.cookie:
                matched = a
                break

    if not matched:
        logger.warning(
            f"[잔액동기화] 매칭 실패: email={body.profileEmail}, username={body.username}"
        )
        return {
            "ok": False,
            "message": f"계정을 찾을 수 없습니다: {body.profileEmail or body.username}",
        }

    from datetime import datetime, timezone

    extra = dict(matched.additional_fields or {})

    if body.expired:
        # 쿠키 만료 처리
        extra["cookie_expired"] = True
        extra["cookie_expired_at"] = datetime.now(timezone.utc).isoformat()
        await svc.repo.update_async(matched.id, additional_fields=extra)
        logger.warning(
            f"[잔액동기화] {matched.account_label}: 쿠키 만료 — 재로그인 필요"
        )
        return {"ok": True, "account_label": matched.account_label, "expired": True}

    # 잔액 + 쿠키 저장
    extra["mileage"] = body.mileage
    extra["cookie_expired"] = False
    if body.cookie:
        extra["musinsa_cookie"] = body.cookie
        extra["cookie_updated_at"] = datetime.now(timezone.utc).isoformat()
    await svc.repo.update_async(
        matched.id,
        balance=body.money,
        balance_updated_at=datetime.now(timezone.utc),
        additional_fields=extra,
    )
    logger.info(
        f"[잔액동기화] {matched.account_label}: 머니 {body.money:,.0f} / 적립금 {body.mileage:,.0f}"
    )
    return {
        "ok": True,
        "account_label": matched.account_label,
        "money": body.money,
        "mileage": body.mileage,
    }


@router.get("/{account_id}/balance")
async def get_balance(
    account_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """계정의 저장된 잔액 조회 (확장앱이 수집한 데이터)."""
    svc = _read_service(session)
    account = await svc.get_account(account_id)
    if not account:
        raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
    extra = account.additional_fields or {}
    return {
        "balance": account.balance,
        "mileage": extra.get("mileage"),
        "balance_updated_at": account.balance_updated_at,
        "cookie_updated_at": extra.get("cookie_updated_at"),
        "has_cookie": bool(extra.get("musinsa_cookie")),
    }
