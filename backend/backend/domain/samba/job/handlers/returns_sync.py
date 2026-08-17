"""returns_sync 잡 핸들러 — 활성 마켓 계정 순회 반품/교환/취소 동기화.

원래 `POST /samba/returns/sync-from-markets` 가 단일 HTTP 요청에서 모든 활성
계정을 순차 처리하며 하나의 write 트랜잭션을 외부 마켓 API 호출 내내 물고 돌던
구조(느림 + Caddy 120s 컷 → 재클릭 → sweep 중첩 + 풀 고갈)를, order_sync 와 동일한
백그라운드 잡으로 분리한 구현.

order_sync.py 를 미러링한다:
    - 계정별 독립 write 세션 (앞 계정 오염 차단, 트랜잭션 짧게)
    - `_CONCURRENCY` 병렬 + 계정별 타임아웃 (hang 계정이 전체를 막지 않음)
    - fresh 세션 진행률 갱신 + 취소 워처
전역 후처리(stale auto-close / shipping_status 일괄 동기화 / 롯데ON 재분류 /
claim 백필)는 계정 수만큼 반복하면 락 경합/데드락이 나므로, 계정 호출은
run_finalize=False 로 스킵하고 모든 계정 완료 후 여기서 1회만 실행한다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.job.model import SambaJob
from backend.domain.samba.job.repository import SambaJobRepository
from backend.domain.samba.job.worker import _add_job_log

logger = logging.getLogger(__name__)

# get_async 로 매칭되지 않는 sentinel — 계정 순회 없이 finalize 만 1회 실행하기 위해
# sync_returns_from_markets(account_id=<이 값>, run_finalize=True) 로 호출한다.
_FINALIZE_ONLY_ACCOUNT_ID = "__returns_finalize_only__"


def _per_account_timeout_seconds(days: int) -> int:
    # 반품 수집은 계정당 11번가/롯데ON(반품·취소·교환 3콜)/스마트스토어/ebay/esm 등
    # 다수 API 가 누적된다. order_sync 와 동일 근거로 180~300초.
    return max(180, min(300, days * 60))


async def run(
    job: SambaJob,
    repo: SambaJobRepository,
    session: AsyncSession,
    worker: Any | None = None,
) -> None:
    """활성 마켓 계정을 순회하며 반품/교환/취소 동기화.

    payload:
        days: int = 30       — 동기화 대상 기간(일)
        account_ids: list[str] | None — 특정 계정만 처리 (미지정 시 활성 전체)
    """
    payload = job.payload or {}
    days = int(payload.get("days") or 30)
    account_ids: list[str] | None = payload.get("account_ids") or None

    # 테넌트 격리: 백그라운드 잡은 tenant ContextVar 가 비어 ORM 자동 필터/INSERT
    # 스탬프가 패스된다. HTTP 경로(get_optional_tenant_id + 미들웨어)와 동일 동작을
    # 위해 job.tenant_id 를 ContextVar 에 세팅한다(cs_sync 와 동일 패턴).
    from backend.core.tenant_context import current_tenant_id

    _tenant_token = current_tenant_id.set(job.tenant_id)

    from backend.api.v1.routers.samba.returns import (
        SyncReturnsRequest,
        sync_returns_from_markets,
    )
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.db.orm import get_write_session

    try:
        # 1) 활성 마켓 계정 조회 — 라우터 sync_returns_from_markets 와 동일 정책
        acc_repo = SambaMarketAccountRepository(session)
        accs = await acc_repo.filter_by_async(
            is_active=True, order_by="created_at", order_by_desc=True
        )
        if job.tenant_id is not None:
            accs = [
                a for a in accs if a.tenant_id == job.tenant_id or a.tenant_id is None
            ]
        if account_ids:
            _id_set = set(account_ids)
            accs = [a for a in accs if a.id in _id_set]

        total = len(accs)
        _add_job_log(
            job.id, f"전체마켓 반품교환 수집 시작 ({total}개 계정, 최근 {days}일)"
        )

        # 초기 진행률 fresh 세션 격리 (order_sync 와 동일, issue #562)
        try:
            async with get_write_session() as _init_s:
                _init_repo = SambaJobRepository(_init_s)
                await _init_repo.update_progress(job.id, 0, total)
                await _init_s.commit()
        except Exception as _ie:
            logger.warning(
                f"[returns_sync] {job.id} 초기 진행률 설정 실패(무시): {_ie}"
            )

        total_synced = 0
        all_results: list[dict[str, Any]] = []
        per_account_timeout = _per_account_timeout_seconds(days)

        _CONCURRENCY = 3
        _sem = asyncio.Semaphore(_CONCURRENCY)
        _done_counter = {"n": 0}
        # _cancel_flag: 워커 루프 제어 신호(신규 계정 시작 중단 + 워처 종료). gather 후
        #   finally 에서도 True 로 세팅되므로 "실제 사용자 취소" 판정에는 쓸 수 없다.
        # _user_cancelled: 사용자가 실제로 취소했는지. 워처에서만 True 로 세팅 →
        #   finalize 스킵 여부는 이 값으로만 판정(#finalize-skip 버그 방지).
        _cancel_flag = {"cancelled": False}
        _user_cancelled = {"v": False}

        async def _process_account(idx: int, acc: Any) -> None:
            if _cancel_flag["cancelled"]:
                return
            async with _sem:
                if _cancel_flag["cancelled"]:
                    return
                label = f"{acc.market_name}({acc.seller_id or '-'})"
                _add_job_log(
                    job.id,
                    f"{label}: 반품교환 수집 시작 ({idx + 1}/{total}, 최근 {days}일, 제한 {per_account_timeout}초)",
                )
                res: dict[str, Any] | None = None
                try:
                    # 계정마다 독립 세션 — 앞 계정 commit/rollback 잔류 오염 차단.
                    # run_finalize=False: 전역 후처리는 모든 계정 완료 후 1회만.
                    async with get_write_session() as acc_session:
                        try:
                            res = await asyncio.wait_for(
                                sync_returns_from_markets(
                                    body=SyncReturnsRequest(
                                        days=days, account_id=acc.id
                                    ),
                                    session=acc_session,
                                    tenant_id=job.tenant_id,
                                    run_finalize=False,
                                ),
                                timeout=per_account_timeout,
                            )
                        except (asyncio.TimeoutError, asyncio.CancelledError):
                            try:
                                await asyncio.wait_for(
                                    acc_session.rollback(), timeout=5
                                )
                            except Exception as _rb_err:
                                logger.warning(
                                    f"[returns_sync] {label} Timeout 후 rollback 실패: {_rb_err}"
                                )
                            raise
                    nonlocal total_synced
                    total_synced += int(res.get("total_synced") or 0)
                    for r in res.get("results") or []:
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
                                job.id,
                                f"{r.get('account', label)}: {r.get('message', '')}",
                            )
                        else:
                            _add_job_log(
                                job.id,
                                f"{r.get('account', label)}: 오류 — {r.get('message', '')}",
                            )
                except asyncio.TimeoutError:
                    logger.error(
                        f"[returns_sync] {label} timeout after {per_account_timeout}s"
                    )
                    _add_job_log(
                        job.id,
                        f"{label} 오류: {per_account_timeout}초 동안 응답이 없어 다음 계정으로 넘어갑니다",
                    )
                    all_results.append(
                        {
                            "account": label,
                            "status": "error",
                            "message": f"timeout after {per_account_timeout}s",
                        }
                    )
                except Exception as e:
                    logger.error(f"[returns_sync] {label} 실패: {e}")
                    _add_job_log(job.id, f"{label} 오류: {e}")
                    all_results.append(
                        {"account": label, "status": "error", "message": str(e)[:500]}
                    )

                _done_counter["n"] += 1
                _done = _done_counter["n"]
                try:
                    async with get_write_session() as prog_session:
                        prog_repo = SambaJobRepository(prog_session)
                        await asyncio.wait_for(
                            prog_repo.update_progress(job.id, _done, total),
                            timeout=5,
                        )
                        await prog_session.commit()
                except (asyncio.TimeoutError, Exception) as pe:
                    logger.warning(
                        f"[returns_sync] {job.id} 진행률 갱신 실패 (계속 진행): {pe}"
                    )

        async def _cancel_watcher() -> None:
            while not _cancel_flag["cancelled"]:
                await asyncio.sleep(5)
                try:
                    if await repo.is_cancelled(job.id):
                        _cancel_flag["cancelled"] = True
                        _user_cancelled["v"] = True
                        _add_job_log(job.id, "사용자 취소 — 신규 계정 시작 중단")
                        return
                except Exception:
                    pass

        _watcher_task = asyncio.create_task(_cancel_watcher())
        try:
            await asyncio.gather(
                *[_process_account(idx, acc) for idx, acc in enumerate(accs)],
                return_exceptions=True,
            )
        finally:
            _cancel_flag["cancelled"] = True
            _watcher_task.cancel()
            try:
                await _watcher_task
            except (asyncio.CancelledError, Exception):
                pass

        # 전역 후처리(finalize) — 모든 계정 완료 후 1회만. 계정 미매칭 sentinel 로
        # 호출해 순회는 스킵하고 finalize 만 실행한다. 실제 사용자 취소 시에만 스킵
        # (_cancel_flag 는 finally 에서도 True 라 finalize 판정에 쓰면 항상 스킵됨).
        if not _user_cancelled["v"]:
            try:
                async with get_write_session() as fin_sync_session:
                    await asyncio.wait_for(
                        sync_returns_from_markets(
                            body=SyncReturnsRequest(
                                days=days, account_id=_FINALIZE_ONLY_ACCOUNT_ID
                            ),
                            session=fin_sync_session,
                            tenant_id=job.tenant_id,
                            run_finalize=True,
                        ),
                        timeout=120,
                    )
                _add_job_log(job.id, "반품/주문 상태 정합 후처리 완료")
            except Exception as _fe:
                logger.warning(
                    f"[returns_sync] {job.id} finalize 후처리 실패(무시): {_fe}"
                )
                _add_job_log(job.id, f"후처리 경고: {_fe}")

        _add_job_log(
            job.id, f"전체마켓 반품교환 수집 완료 — 총 {total_synced}건 신규 저장"
        )
    finally:
        current_tenant_id.reset(_tenant_token)

    # 잡 완료 — 독립 fresh 세션에서 즉시 commit (워커 세션 hang → running 고착 방지)
    try:
        async with get_write_session() as fin_session:
            fin_repo = SambaJobRepository(fin_session)
            await asyncio.wait_for(
                fin_repo.complete_job(
                    job.id,
                    result={"total_synced": total_synced, "results": all_results},
                ),
                timeout=10,
            )
            await fin_session.commit()
    except Exception as fe:
        logger.error(
            f"[returns_sync] {job.id} 최종 commit 실패 — 워커 세션 fallback: {fe}"
        )
        await repo.complete_job(
            job.id,
            result={"total_synced": total_synced, "results": all_results},
        )
