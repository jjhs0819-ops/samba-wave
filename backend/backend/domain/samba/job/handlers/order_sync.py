"""order_sync 잡 핸들러 — 활성 마켓 계정 순회 주문 동기화.

원래 `POST /samba/orders/sync-from-markets` 가 단일 요청에서 모든 활성 계정을
순차 처리하던 구조를, 백그라운드 잡으로 분리한 구현.

Caddy `response_header_timeout 120s` 우회 + 진행률 폴링 + 취소 가능.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.job.model import SambaJob
from backend.domain.samba.job.repository import SambaJobRepository
from backend.domain.samba.job.worker import _add_job_log

logger = logging.getLogger(__name__)


async def run(
    job: SambaJob,
    repo: SambaJobRepository,
    session: AsyncSession,
    worker: Any | None = None,
) -> None:
    """활성 마켓 계정을 순회하며 라우터 함수를 직접 호출해 주문 동기화.

    payload:
        days: int = 7        — 동기화 대상 기간(일)
        account_ids: list[str] | None — 특정 계정만 처리 (미지정 시 활성 전체)

    동작:
        1) 활성 계정 목록 조회 (tenant_id 격리)
        2) 진행률 초기화 (total = 계정 수)
        3) 각 계정에 대해 sync_orders_from_markets(account_id=acc.id) 직접 호출
           — 라우터 함수의 1,461줄 로직(스마트스토어/쿠팡/eBay/롯데ON 등)을 그대로 재사용
        4) 매 계정 후 progress 갱신 + 취소 체크
        5) complete_job(result={total_synced, results})
    """
    payload = job.payload or {}
    days = int(payload.get("days") or 7)
    account_ids: list[str] | None = payload.get("account_ids") or None

    # 1) 활성 마켓 계정 조회 — 라우터의 1864-1891 로직과 동일한 정책
    from backend.domain.samba.account.repository import SambaMarketAccountRepository

    acc_repo = SambaMarketAccountRepository(session)
    accs = await acc_repo.filter_by_async(
        is_active=True, order_by="created_at", order_by_desc=True
    )
    # 테넌트 격리: 잡의 tenant_id 가 있으면 해당 테넌트 계정 + 공용(None) 만 유지
    if job.tenant_id is not None:
        accs = [a for a in accs if a.tenant_id == job.tenant_id or a.tenant_id is None]
    # 특정 계정만 지정한 경우 추가 필터
    if account_ids:
        _id_set = set(account_ids)
        accs = [a for a in accs if a.id in _id_set]

    total = len(accs)
    _add_job_log(job.id, f"전체마켓 주문수집 시작 ({total}개 계정, 최근 {days}일)")
    job.total = total
    job.current = 0
    job.progress = 0
    session.add(job)
    await session.flush()

    # 라우터 함수 직접 호출(Depends 우회) — 라우터 변경 0
    from backend.api.v1.routers.samba.order import (
        sync_orders_from_markets,
        SyncOrdersRequest,
    )

    total_synced = 0
    all_results: list[dict[str, Any]] = []

    for idx, acc in enumerate(accs):
        # 사용자 취소 체크 — 매 계정 시작 전
        if await repo.is_cancelled(job.id):
            logger.info(f"[order_sync] {job.id} 취소 감지 — 중단")
            _add_job_log(job.id, "사용자 취소 — 동기화 중단")
            return

        label = f"{acc.market_name}({acc.seller_id or '-'})"
        try:
            res = await sync_orders_from_markets(
                body=SyncOrdersRequest(days=days, account_id=acc.id),
                session=session,
                tenant_id=job.tenant_id,
            )
            total_synced += int(res.get("total_synced") or 0)
            results = res.get("results") or []
            for r in results:
                all_results.append(r)
                if r.get("status") == "success":
                    _add_job_log(
                        job.id,
                        f"{r.get('account', label)}: "
                        f"{r.get('fetched', 0)}건 조회, "
                        f"{r.get('synced', 0)}건 신규 저장",
                    )
                elif r.get("status") == "skip":
                    _add_job_log(
                        job.id, f"{r.get('account', label)}: {r.get('message', '')}"
                    )
                else:
                    _add_job_log(
                        job.id,
                        f"{r.get('account', label)}: 오류 — {r.get('message', '')}",
                    )
        except Exception as e:
            logger.error(f"[order_sync] {label} 실패: {e}")
            _add_job_log(job.id, f"{label} 오류: {e}")
            all_results.append(
                {"account": label, "status": "error", "message": str(e)[:500]}
            )
            # 라우터 함수가 자체 rollback 하지만 핸들러에서도 안전 보장
            try:
                await session.rollback()
            except Exception:
                pass

        # 진행률 갱신 — 매 계정 처리 후
        await repo.update_progress(job.id, idx + 1, total)

    _add_job_log(job.id, f"전체마켓 주문수집 완료 — 총 {total_synced}건 신규 저장")

    # 잡 완료 — worker 가 finally 에서 commit 함
    await repo.complete_job(
        job.id,
        result={"total_synced": total_synced, "results": all_results},
    )
