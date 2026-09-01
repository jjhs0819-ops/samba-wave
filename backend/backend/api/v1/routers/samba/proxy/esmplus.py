"""ESMPlus(지마켓/옥션) 배송정보 조회 프록시."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency
from backend.utils.logger import logger

router = APIRouter(tags=["samba-proxy-esm"])


async def _get_esm_client(
    session: AsyncSession,
    market: str,
    account_id: str | None,
):
    """계정 정보로 ESMPlusClient 생성.

    인증 정보 우선순위 (resolve_esm_credentials):
      account.additional_fields > samba_settings.esm_credentials > env.
    """
    from backend.domain.samba.proxy.esmplus import (
        ESMPlusClient,
        resolve_esm_credentials,
    )
    from sqlalchemy import text

    if market not in ("gmarket", "auction"):
        return None

    if account_id:
        result = await session.exec(
            text(
                "SELECT seller_id, additional_fields FROM samba_market_account "
                "WHERE id = :aid AND market_type = :mtype AND is_active = true"
            ).bindparams(aid=account_id, mtype=market)
        )
    else:
        # 계정 미지정 폴백 — ORDER BY 없는 LIMIT 1 은 어느 계정이 걸릴지 보장이 없어,
        # 다계정 운영에서 엉뚱한 사업자의 출고지·발송정책을 보여줄 수 있다.
        # 기본 계정(is_default) 우선, 그다음 가장 먼저 등록된 계정으로 고정한다.
        result = await session.exec(
            text(
                "SELECT seller_id, additional_fields FROM samba_market_account "
                "WHERE market_type = :mtype AND is_active = true "
                "ORDER BY is_default DESC, created_at ASC LIMIT 1"
            ).bindparams(mtype=market)
        )

    row = result.first()
    if not row:
        return None

    seller_id = row[0] or ""
    if not seller_id:
        return None

    # account.additional_fields 기반 인증 시도 (없으면 env fallback)
    class _AccountStub:
        def __init__(self, additional_fields: dict | None) -> None:
            self.additional_fields = additional_fields or {}

    account_stub = _AccountStub(row[1] if len(row) > 1 else None)
    hosting_id, secret_key = await resolve_esm_credentials(session, account_stub)
    if not hosting_id or not secret_key:
        return None

    return ESMPlusClient(hosting_id, secret_key, seller_id, site=market)


@router.get("/esm/{market}/delivery-info")
async def esm_delivery_info(
    market: str,
    account_id: str | None = None,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """ESMPlus 출고지/반품지/발송정책 목록 조회."""
    if market not in ("gmarket", "auction"):
        return {
            "success": False,
            "places": [],
            "dispatchPolicies": [],
            "message": "지원하지 않는 마켓",
        }

    try:
        client = await _get_esm_client(session, market, account_id)
        if not client:
            return {
                "success": False,
                "places": [],
                "dispatchPolicies": [],
                "message": "계정 정보가 없거나 서버 환경변수(ESMPLUS_HOSTING_ID/ESMPLUS_SECRET_KEY)가 설정되지 않았습니다.",
            }

        places, dispatch_policies = await asyncio.gather(
            client.get_places(),
            client.get_dispatch_policies(),
            return_exceptions=True,
        )

        # 실패를 빈 리스트로 뭉개고 success=True 를 돌려주면 화면에 초록색
        # "0개를 불러왔습니다" 가 떠서 401(셀링툴 미인증)·판매자ID 오타를 구분할 수
        # 없다. 하나라도 실패하면 사유를 그대로 올린다.
        errors: list[str] = []
        if isinstance(places, Exception):
            logger.warning(f"[ESMPlus/{market}] 출고지 조회 실패: {places}")
            errors.append(f"출고지: {places}")
            places = []
        if isinstance(dispatch_policies, Exception):
            logger.warning(
                f"[ESMPlus/{market}] 발송정책 조회 실패: {dispatch_policies}"
            )
            errors.append(f"발송정책: {dispatch_policies}")
            dispatch_policies = []

        if errors:
            return {
                "success": False,
                "places": places,
                "dispatchPolicies": dispatch_policies,
                "message": f"[{client.seller_id}] 조회 실패 — " + " / ".join(errors),
            }

        return {
            "success": True,
            "places": places,
            "dispatchPolicies": dispatch_policies,
        }
    except Exception as exc:
        logger.error(f"[ESMPlus/{market}] 배송정보 조회 실패: {exc}")
        return {
            "success": False,
            "places": [],
            "dispatchPolicies": [],
            "message": str(exc),
        }
