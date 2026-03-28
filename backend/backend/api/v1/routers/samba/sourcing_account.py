"""소싱처 계정 API 라우터."""

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.dtos.samba.sourcing_account import SourcingAccountCreate, SourcingAccountUpdate
from backend.utils.logger import logger

router = APIRouter(prefix="/sourcing-accounts", tags=["samba-sourcing-accounts"])


def _read_service(session: AsyncSession):
    from backend.domain.samba.sourcing_account.repository import SambaSourcingAccountRepository
    from backend.domain.samba.sourcing_account.service import SambaSourcingAccountService
    return SambaSourcingAccountService(SambaSourcingAccountRepository(session))


def _write_service(session: AsyncSession):
    from backend.domain.samba.sourcing_account.repository import SambaSourcingAccountRepository
    from backend.domain.samba.sourcing_account.service import SambaSourcingAccountService
    return SambaSourcingAccountService(SambaSourcingAccountRepository(session))


@router.get("")
async def list_sourcing_accounts(
    site_name: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    return await _read_service(session).list_accounts(site_name=site_name)


@router.get("/sites")
async def get_supported_sites():
    from backend.domain.samba.sourcing_account.service import SambaSourcingAccountService
    return SambaSourcingAccountService.get_supported_sites()


@router.get("/chrome-profiles")
async def get_chrome_profiles():
    """PC에 존재하는 크롬 프로필 목록 반환."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    local_state_path = Path(local_app_data) / "Google" / "Chrome" / "User Data" / "Local State"
    if not local_state_path.exists():
        return []
    try:
        data = json.loads(local_state_path.read_text(encoding="utf-8"))
        profiles_info = data.get("profile", {}).get("info_cache", {})
        results = []
        for directory, info in profiles_info.items():
            results.append({
                "directory": directory,
                "name": info.get("name", directory),
                "gaia_name": info.get("gaia_name", ""),
            })
        return sorted(results, key=lambda x: x["directory"])
    except Exception as e:
        logger.warning(f"크롬 프로필 목록 조회 실패: {e}")
        return []


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
):
    return await _write_service(session).create_account(body.model_dump(exclude_unset=True))


@router.put("/{account_id}")
async def update_sourcing_account(
    account_id: str,
    body: SourcingAccountUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    result = await svc.update_account(account_id, body.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
    return result


@router.put("/{account_id}/toggle")
async def toggle_sourcing_account(
    account_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    result = await _write_service(session).toggle_active(account_id)
    if not result:
        raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
    return result


@router.delete("/{account_id}")
async def delete_sourcing_account(
    account_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    if not await _write_service(session).delete_account(account_id):
        raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
    return {"ok": True}


@router.post("/{account_id}/fetch-balance")
async def fetch_balance(
    account_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """단건 잔액 조회."""
    svc = _write_service(session)
    account = await svc.get_account(account_id)
    if not account:
        raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
    if not account.chrome_profile:
        raise HTTPException(400, "크롬 프로필이 설정되지 않았습니다")
    try:
        balance = await _fetch_musinsa_balance(account)
        updated = await svc.update_balance(account_id, balance)
        return {"balance": balance, "account": updated}
    except Exception as e:
        logger.error(f"잔액 조회 실패 [{account.account_label}]: {e}")
        raise HTTPException(500, f"잔액 조회 실패: {str(e)}")


@router.post("/fetch-all-balances")
async def fetch_all_balances(
    site_name: str = Query("MUSINSA"),
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """특정 소싱처의 전체 활성 계정 잔액 일괄 조회."""
    svc = _write_service(session)
    accounts = await svc.list_accounts(site_name=site_name)
    active = [a for a in accounts if a.is_active and a.chrome_profile]
    results = []
    for account in active:
        try:
            balance = await _fetch_musinsa_balance(account)
            await svc.update_balance(account.id, balance)
            results.append({"id": account.id, "label": account.account_label, "balance": balance, "status": "success"})
        except Exception as e:
            logger.error(f"잔액 조회 실패 [{account.account_label}]: {e}")
            results.append({"id": account.id, "label": account.account_label, "balance": None, "status": "error", "message": str(e)})
    return {"results": results}


async def _fetch_musinsa_balance(account) -> float:
    """무신사 로그인 → 마이페이지에서 무신사머니 잔액을 파싱한다."""
    import re
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        page = await browser.new_page()
        try:
            # 마이페이지 접속 → 로그인 페이지로 리다이렉트
            await page.goto("https://www.musinsa.com/app/mypage", wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)

            # 로그인
            if "login" in page.url:
                await page.fill('input[type="text"]', account.username)
                await page.fill('input[type="password"]', account.password)
                await page.click('button[type="submit"]')
                await page.wait_for_timeout(3000)
                if "login" in page.url:
                    raise Exception("로그인 실패 — 캡챠 또는 인증 필요")

            # 잔액이 표시되는 마이페이지
            await page.goto("https://www.musinsa.com/mypage", wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(3000)

            content = await page.content()

            # 무신사머니 파싱: "무신사머니" 텍스트 근처의 금액
            match = re.search(r'무신사머니.*?([\d,]+)\s*원', content, re.DOTALL)
            if match:
                balance = int(match.group(1).replace(',', ''))
                logger.info(f"[잔액조회] {account.account_label}: 무신사머니 {balance:,}원")
                return float(balance)

            # 대체: 페이지에서 "원" 붙은 금액 모두 추출
            amounts = re.findall(r'([\d,]+)\s*원', content)
            if amounts:
                # 가장 큰 금액을 무신사머니로 추정
                nums = [int(a.replace(',', '')) for a in amounts]
                balance = max(nums)
                logger.info(f"[잔액조회] {account.account_label}: 추정 잔액 {balance:,}원")
                return float(balance)

            raise Exception("무신사머니 잔액을 찾을 수 없습니다")
        finally:
            await browser.close()
