"""백그라운드 잡 워커 — FastAPI lifespan에서 실행.

재시작 시 stuck running 잡 자동 복구 포함.
"""

import asyncio
import ctypes
import gc
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

from backend.domain.samba.job.model import JobStatus

logger = logging.getLogger(__name__)
UTC = timezone.utc


def _force_free_memory():
    """gc.collect() + glibc malloc_trim으로 해제된 메모리를 OS에 반환."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass  # Windows/macOS에서는 무시


# Job별 실시간 로그 버퍼 (인메모리, 최근 500줄)
_job_logs: dict[str, list[str]] = {}
_MAX_JOB_LOGS = 5000  # 인덱스 기반 since 폴링이므로 리스트 사용 (deque는 인덱스 어긋남)

# ── 전송 로그 전용 링 버퍼 (오토튠과 동일 방식) ──
_shipment_log_buffer: deque[str] = deque(maxlen=300)
_shipment_log_total: int = 0  # 누적 카운터


def get_shipment_logs(since_idx: int = 0) -> tuple[list[str], int]:
    """전송 로그 링 버퍼 조회 (since_idx 이후). (logs, current_idx) 반환."""
    global _shipment_log_total
    buf_len = len(_shipment_log_buffer)
    buf_start = _shipment_log_total - buf_len
    if since_idx >= _shipment_log_total:
        return [], _shipment_log_total
    if since_idx <= buf_start:
        logs = list(_shipment_log_buffer)
    else:
        offset = since_idx - buf_start
        logs = list(_shipment_log_buffer)[offset:]
    return logs, _shipment_log_total


def _add_shipment_log(msg: str):
    """전송 로그를 링 버퍼에 추가."""
    global _shipment_log_total
    _shipment_log_buffer.append(msg)
    _shipment_log_total += 1


def clear_shipment_logs():
    """전송 로그 링 버퍼 초기화 (사용자 요청 시만)."""
    global _shipment_log_total
    _shipment_log_buffer.clear()
    _shipment_log_total = 0


def get_job_logs(job_id: str, since: int = 0) -> list[str]:
    """Job 로그 조회 (since 인덱스 이후)."""
    buf = _job_logs.get(job_id)
    if not buf:
        return []
    return buf[since:]


def _add_job_log(job_id: str, msg: str):
    """Job 로그 추가 (최대 _MAX_JOB_LOGS 유지) + 전송 링 버퍼에도 저장."""
    # 백엔드 타임스탬프 (KST) — 프론트 폴링 시각이 아닌 실제 처리 시각 기록
    from datetime import datetime as _dt, timezone, timedelta

    msg = f"[{(_dt.now(timezone.utc) + timedelta(hours=9)).strftime('%H:%M:%S')}] {msg}"
    if job_id not in _job_logs:
        _job_logs[job_id] = []
    buf = _job_logs[job_id]
    buf.append(msg)
    if len(buf) > _MAX_JOB_LOGS:
        _job_logs[job_id] = buf[-_MAX_JOB_LOGS:]
    # 전송 링 버퍼에도 동시 저장
    _add_shipment_log(msg)


def clear_job_logs(job_id: str):
    """완료된 잡 로그 삭제 — 메모리 해제 (링 버퍼는 유지)."""
    _job_logs.pop(job_id, None)


# 워커 상태 추적 (health 엔드포인트용)
_worker_status: dict[str, str | None] = {
    "alive": "false",
    "last_poll": None,
    "started_at": None,
    "restarts": "0",
}


def get_worker_status() -> dict[str, str | None]:
    """현재 워커 상태 반환."""
    return dict(_worker_status)


def _run_collect_in_thread(worker: "JobWorker", job_id: str, payload: dict):
    """별도 스레드에서 독립 이벤트 루프로 수집 실행."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(worker._execute_collect_isolated(job_id, payload))
    except Exception as e:
        logger.error(f"[잡워커] 수집 스레드 에러: {job_id} — {e}")
    finally:
        loop.close()


def _run_transmit_in_thread(worker: "JobWorker", job_id: str, payload: dict):
    """별도 스레드에서 독립 이벤트 루프로 전송 실행 — API 요청과 I/O 완전 격리."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(worker._execute_transmit_isolated(job_id, payload))
    except Exception as e:
        logger.error(f"[잡워커] 전송 스레드 에러: {job_id} — {e}")
    finally:
        loop.close()


class JobWorker:
    """pending 잡을 폴링하여 순차 실행."""

    POLL_INTERVAL = 5  # 초

    STUCK_CHECK_INTERVAL = 6  # 6회 폴링마다 stuck 체크 (≒30초)
    STUCK_THRESHOLD_SEC = 300  # 5분 이상 progress 변화 없으면 stuck 판정

    def __init__(self):
        self._running = True
        self._shutting_down = False  # SIGTERM 수신 시 True — 전송 루프가 체크
        self._active_types: set[str] = set()  # 현재 실행 중인 잡 타입
        self._active_job_id: str | None = None  # 현재 실행 중인 잡 ID (shutdown 복구용)
        self._poll_count = 0

    async def start(self):
        """무한 루프: pending 잡 조회 → 타입별 병렬 실행."""
        logger.info("[잡워커] 시작 (병렬 모드: collect/transmit 동시 실행)")
        _worker_status["alive"] = "true"
        _worker_status["started_at"] = datetime.now(UTC).isoformat()
        _worker_status["restarts"] = str(int(_worker_status.get("restarts") or 0) + 1)
        # 배포/재시작으로 stuck된 running 잡 자동 복구
        await self._recover_stuck_jobs()
        while self._running:
            try:
                # 주기적 stuck 잡 복구 (배포/DB 끊김 후 running 상태로 남은 잡)
                self._poll_count += 1
                if self._poll_count % self.STUCK_CHECK_INTERVAL == 0:
                    await self._recover_stuck_jobs()
                executed = await self._poll_once()
                if not executed:
                    await asyncio.sleep(self.POLL_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[잡워커] 폴링 에러: {e}")
                await asyncio.sleep(self.POLL_INTERVAL)
        _worker_status["alive"] = "false"
        logger.info("[잡워커] 종료")

    async def _recover_stuck_jobs(self):
        """stuck running 잡을 pending으로 복구 — 현재 워커가 실행 중인 타입은 제외."""
        try:
            from backend.db.orm import get_write_session
            from backend.domain.samba.job.repository import SambaJobRepository

            async with get_write_session() as session:
                repo = SambaJobRepository(session)
                recovered = await repo.recover_stuck_running(
                    exclude_types=self._active_types,
                    threshold_sec=self.STUCK_THRESHOLD_SEC,
                )
                if recovered:
                    await session.commit()
                    logger.info(
                        f"[잡워커] stuck running 잡 {recovered}건 → pending 복구"
                    )
        except Exception as e:
            logger.warning(f"[잡워커] stuck 잡 복구 실패: {e}")

    def stop(self):
        self._running = False

    async def graceful_stop(self, timeout: int = 30):
        """배포 시 호출 — 전송 루프에 종료 신호 보내고 대기.

        1) _shutting_down 플래그 세팅 → 전송 루프가 현재 건 완료 후 탈출
        2) 최대 timeout초 대기 → 전송 루프 종료 확인
        3) running transmit Job → pending으로 전환 (current 보존)
        """
        self._shutting_down = True
        self._running = False
        logger.info("[잡워커] graceful_stop — 전송 루프 종료 대기")

        # 전송 루프가 자연 종료될 때까지 대기
        for _ in range(timeout):
            if not self._active_types:
                break
            await asyncio.sleep(1)

        # running 상태인 transmit Job → pending 복구 (current 보존, attempt 유지)
        if self._active_job_id:
            try:
                from backend.db.orm import get_write_session
                from sqlalchemy import text

                async with get_write_session() as session:
                    await session.execute(
                        text(
                            "UPDATE samba_jobs SET status = 'pending', "
                            "started_at = NULL "
                            "WHERE id = :jid AND status = 'running'"
                        ),
                        {"jid": self._active_job_id},
                    )
                    await session.commit()
                    logger.info(
                        f"[잡워커] 배포 종료 — 잡 {self._active_job_id} → pending 복구"
                    )
            except Exception as e:
                logger.error(f"[잡워커] 배포 종료 잡 복구 실패: {e}")

    async def _poll_once(self) -> bool:
        """OOM 방지: 한 번에 1개 잡만 실행 (수집+전송 동시 실행 차단)."""
        _worker_status["last_poll"] = datetime.now(UTC).isoformat()
        from backend.db.orm import get_write_session
        from backend.domain.samba.job.repository import SambaJobRepository

        async with get_write_session() as session:
            repo = SambaJobRepository(session)
            jobs = await repo.list_pending(limit=5)
            if not jobs:
                return False

            # OOM 방지: 이미 실행 중인 잡이 있으면 대기
            if self._active_types:
                for job in jobs:
                    job.status = JobStatus.PENDING
                    job.started_at = None
                await session.commit()
                return False

            # 1개만 선택, 나머지는 pending으로 되돌림
            selected = jobs[0]
            self._active_types.add(selected.job_type)
            for job in jobs[1:]:
                job.status = JobStatus.PENDING
                job.started_at = None

            await session.commit()

        # 1개 잡만 실행
        await self._execute_job(selected)
        return True

    async def _execute_job(self, job):
        """개별 잡 실행 — 수집만 별도 스레드, 전송+기타는 메인 루프."""
        from backend.db.orm import get_write_session
        from backend.domain.samba.job.repository import SambaJobRepository

        try:
            # 수집: 별도 스레드 + 독립 이벤트 루프 (전송과 I/O 격리)
            _job_id = job.id
            _job_type = job.job_type
            _job_payload = job.payload or {}
            if _job_type == "collect":
                logger.info(f"[잡워커] 수집 실행 (격리 스레드): {_job_id}")
                thread = threading.Thread(
                    target=_run_collect_in_thread,
                    args=(self, _job_id, _job_payload),
                    daemon=True,
                )
                thread.start()
                elapsed = 0
                while thread.is_alive() and elapsed < 600:
                    if self._shutting_down:
                        logger.info(
                            f"[잡워커] 배포 종료 — 수집 스레드 대기 중단: {_job_id}"
                        )
                        break
                    await asyncio.sleep(2)
                    elapsed += 2
                if thread.is_alive():
                    logger.error(f"[잡워커] 수집 스레드 10분 타임아웃: {_job_id}")
                    _add_job_log(_job_id, "수집 타임아웃 (10분)")
                    # 잡 상태를 failed로 갱신
                    try:
                        async with get_write_session() as timeout_session:
                            from backend.domain.samba.job.repository import (
                                SambaJobRepository,
                            )

                            timeout_repo = SambaJobRepository(timeout_session)
                            await timeout_repo.fail_job(_job_id, "수집 타임아웃 (10분)")
                            await timeout_session.commit()
                    except Exception as te:
                        logger.error(f"[잡워커] 타임아웃 잡 상태 갱신 실패: {te}")
                return

            # 전송 + 기타: 메인 루프 직접 실행 (인메모리 로그 공유)
            _job_id = job.id
            _job_type = job.job_type
            self._active_job_id = _job_id
            async with get_write_session() as session:
                repo = SambaJobRepository(session)
                # detached 객체 대신 현재 세션에서 job 재조회
                from backend.domain.samba.job.model import SambaJob as _SJ

                fresh_job = await session.get(_SJ, _job_id)
                if not fresh_job:
                    logger.error(f"[잡워커] 잡 재조회 실패: {_job_id}")
                    return
                logger.info(f"[잡워커] 실행: {_job_id} ({_job_type})")

                try:
                    if _job_type == "transmit":
                        await self._run_transmit(fresh_job, repo, session)
                    elif _job_type == "refresh":
                        await self._run_stub(fresh_job, repo, "갱신")
                    elif _job_type == "ai_tag":
                        await self._run_stub(fresh_job, repo, "AI태그")
                    else:
                        await repo.fail_job(_job_id, f"알 수 없는 잡 타입: {_job_type}")

                    await session.commit()
                except Exception as e:
                    logger.error(f"[잡워커] 잡 실행 실패: {_job_id} — {e}")
                    try:
                        await repo.fail_job(_job_id, str(e))
                        await session.commit()
                    except Exception as fail_exc:
                        logger.error(
                            f"[잡워커] 잡 상태 갱신 실패 (running 고착 가능): {_job_id} — {fail_exc}"
                        )
        finally:
            self._active_job_id = None
            self._active_types.discard(_job_type)
            # 프론트 폴링이 로그를 읽을 시간 확보 후 삭제 (60초)
            try:
                asyncio.get_running_loop().call_later(60, clear_job_logs, _job_id)
            except RuntimeError:
                pass  # 루프 종료 중이면 로그 정리 스킵

    async def _execute_collect_isolated(self, job_id: str, payload: dict):
        """격리된 이벤트 루프에서 수집 잡 실행 — 자체 DB 세션 관리."""
        from backend.db.orm import get_write_session
        from backend.domain.samba.job.repository import SambaJobRepository
        from backend.domain.samba.job.model import SambaJob

        try:
            async with get_write_session() as session:
                repo = SambaJobRepository(session)
                job = await session.get(SambaJob, job_id)
                if not job:
                    logger.error(f"[잡워커] 수집 잡 없음: {job_id}")
                    return
                try:
                    await self._run_collect(job, repo, session)
                    await session.commit()
                except Exception as e:
                    logger.error(f"[잡워커] 수집 실행 실패: {job_id} — {e}")
                    try:
                        await repo.fail_job(job_id, str(e))
                        await session.commit()
                    except Exception as fail_exc:
                        logger.error(
                            f"[잡워커] 잡 상태 갱신 실패 (running 고착 가능): {job_id} — {fail_exc}"
                        )
        except Exception as e:
            logger.error(f"[잡워커] 수집 세션 에러: {job_id} — {e}")

    async def _execute_transmit_isolated(self, job_id: str, payload: dict):
        """격리된 이벤트 루프에서 전송 잡 실행 — 자체 DB 세션 관리."""
        from backend.db.orm import get_write_session
        from backend.domain.samba.job.repository import SambaJobRepository
        from backend.domain.samba.job.model import SambaJob

        # 별도 이벤트 루프이므로 이전 루프의 세마포어 정리
        from backend.domain.samba.shipment.service import clear_account_semaphores

        clear_account_semaphores()

        try:
            async with get_write_session() as session:
                repo = SambaJobRepository(session)
                job = await session.get(SambaJob, job_id)
                if not job:
                    logger.error(f"[잡워커] 전송 잡 없음: {job_id}")
                    return
                try:
                    await self._run_transmit(job, repo, session)
                    await session.commit()
                except Exception as e:
                    logger.error(f"[잡워커] 전송 실행 실패: {job_id} — {e}")
                    try:
                        await repo.fail_job(job_id, str(e))
                        await session.commit()
                    except Exception as fail_exc:
                        logger.error(
                            f"[잡워커] 잡 상태 갱신 실패 (running 고착 가능): {job_id} — {fail_exc}"
                        )
        except Exception as e:
            logger.error(f"[잡워커] 전송 세션 에러: {job_id} — {e}")

    async def _run_transmit(self, job, repo, session):
        """전송 잡 실행 — 기존 shipment_service 호출."""
        from backend.domain.samba.shipment.service import (
            SambaShipmentService,
            is_cancel_requested,
            clear_cancel_transmit,
            clear_account_semaphores,
        )
        from backend.domain.samba.shipment.repository import SambaShipmentRepository

        # 이전 전송의 잔류 세마포어/상품 락 강제 해제
        clear_account_semaphores()
        from backend.domain.samba.emergency import clear_emergency_stop

        # 이전 취소/비상정지 잔존 플래그 해제 (새 전송은 항상 정상 시작)
        clear_cancel_transmit()
        clear_emergency_stop()

        payload = job.payload or {}
        product_ids = payload.get("product_ids", [])
        update_items = payload.get("update_items", [])
        target_account_ids = payload.get("target_account_ids", [])
        skip_unchanged = payload.get("skip_unchanged", False)

        if not product_ids:
            await repo.fail_job(job.id, "product_ids 없음")
            return

        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )
        from backend.domain.samba.account.repository import SambaMarketAccountRepository
        from backend.db.orm import get_write_session

        total = len(product_ids)

        # 이어하기: 이전 진행 위치를 먼저 읽은 후 진행률 갱신
        # (update_progress가 identity map으로 job.current를 덮어쓰기 때문)
        start_from = job.current or 0
        await repo.update_progress(job.id, start_from, total)

        # 이어하기: 이전 실행의 카운트 복원
        prev_result = job.result or {}
        success_count = prev_result.get("success", 0) if start_from > 0 else 0
        fail_count = prev_result.get("failed", 0) if start_from > 0 else 0
        skip_count = prev_result.get("skipped", 0) if start_from > 0 else 0
        failed_pids: list[str] = []  # 재시도 대상

        # 상품별 전송 루프
        if start_from > 0:
            _add_job_log(job.id, f"이전 진행 {start_from}/{total}건 이후부터 재개")
            logger.info(f"[잡워커] 전송 재개: {job.id} — {start_from}/{total}건부터")
        for i, pid in enumerate(product_ids[start_from:], start=start_from):
            # 비상정지 + Job 취소 + 전송중단 플래그 체크 (건별)
            from backend.domain.samba.emergency import is_emergency_stopped

            try:
                _is_cancelled = await repo.is_cancelled(job.id)
            except Exception:
                _is_cancelled = False

            # 배포 종료 감지 — progress 저장 후 정상 탈출 (pending 유지)
            if self._shutting_down:
                remaining = len(product_ids) - i
                _add_job_log(
                    job.id,
                    f"배포 종료 — {i}건 완료, {remaining}건 남음 (다음 인스턴스에서 재개)",
                )
                logger.info(
                    f"[잡워커] 배포 종료 감지: {job.id} — {i}/{total}건, pending 유지"
                )
                try:
                    await repo.update_progress(job.id, i, total)
                    await session.commit()
                except Exception:
                    pass
                return  # fail 아닌 정상 리턴 — graceful_stop이 pending으로 전환

            if is_emergency_stopped() or is_cancel_requested() or _is_cancelled:
                cancelled = len(product_ids) - i
                reason = "비상정지" if is_emergency_stopped() else "취소"
                _add_job_log(job.id, f"{reason} — {i}건 완료, {cancelled}건 중단")
                logger.info(
                    f"[잡워커] 전송 {reason}: {job.id} — {i}건 완료, {cancelled}건 중단"
                )
                await repo.fail_job(job.id, f"{reason}: {i}건 완료, {cancelled}건 중단")
                return

            # 건별 독립 세션 — greenlet_spawn 방지 (세션 상태 누적 차단)
            prod_name = pid[-8:]  # 기본값 — 세션 실패 시 폴백
            try:
                async with get_write_session() as item_session:
                    cp_repo = SambaCollectedProductRepository(item_session)
                    acc_repo = SambaMarketAccountRepository(item_session)
                    prod = await cp_repo.get_async(pid)
                    site_pid = prod.site_product_id if prod else ""
                    _brand = (prod.brand or "") if prod else ""
                    _style = (prod.style_code or "") if prod else ""
                    _raw_name = (prod.name or "") if prod else pid[-8:]
                    prod_name = f"{_brand} {_raw_name}".strip()[:35]
                    if _style:
                        prod_name = f"{prod_name} {_style}"
                    if site_pid:
                        prod_name = f"{prod_name} ({site_pid})"

                    item_svc = SambaShipmentService(
                        SambaShipmentRepository(item_session), item_session
                    )
                    result = await item_svc.start_update(
                        [pid],
                        update_items,
                        target_account_ids,
                        skip_unchanged=skip_unchanged,
                    )
                    results_list = result.get("results", [])
                    r = results_list[0] if results_list else {}
                    status = r.get("status", "unknown")
                    tx_result = r.get("transmit_result", {})
                    tx_error = r.get("transmit_error", {})
                    any_success = False
                    for acc_id, acc_status in tx_result.items():
                        acc = await acc_repo.get_async(acc_id)
                        acc_label = (
                            f"{acc.market_name}({acc.seller_id or acc.business_name or '-'})"
                            if acc
                            else acc_id
                        )
                        ur = r.get("update_result", {})
                        rl = (
                            f" [{ur.get('refresh', '')}]"
                            if isinstance(ur, dict) and ur.get("refresh")
                            else ""
                        )
                        if acc_status == "success":
                            any_success = True
                            success_count += 1
                            _add_job_log(
                                job.id,
                                f"[{i + 1}/{total:,}] {prod_name} → {acc_label}: 전송{rl}",
                            )
                        elif acc_status == "skipped":
                            skip_count += 1
                            _add_job_log(
                                job.id,
                                f"[{i + 1}/{total:,}] {prod_name} → {acc_label}: 스킵{rl}",
                            )
                        else:
                            fail_count += 1
                            err = str(tx_error.get(acc_id, "실패"))[:60]
                            if "<asyncio" in err or "Semaphore" in err:
                                err = "전송 동시성 오류"
                            _add_job_log(
                                job.id,
                                f"[{i + 1}/{total:,}] {prod_name} → {acc_label}: {err}",
                            )
                    if not tx_result:
                        if status == "skipped":
                            skip_count += 1
                            refresh_info = r.get("update_result", {})
                            rl = (
                                refresh_info.get("refresh", "")
                                if isinstance(refresh_info, dict)
                                else ""
                            )
                            _add_job_log(
                                job.id, f"[{i + 1}/{total}] {prod_name}: 스킵 [{rl}]"
                            )
                        elif r.get("error") or tx_error.get("_all"):
                            fail_count += 1
                            err_msg = r.get("error") or tx_error.get("_all", "실패")
                            _add_job_log(
                                job.id,
                                f"[{i + 1}/{total}] {prod_name}: {str(err_msg)[:60]}",
                            )
                        else:
                            fail_count += 1
                            _add_job_log(job.id, f"[{i + 1}/{total}] {prod_name}: 실패")
                    # 1차 실패 → 재시도 대상
                    if not any_success and status not in ("skipped", "completed"):
                        failed_pids.append(pid)
                    await item_session.commit()
            except Exception as e:
                fail_count += 1
                _add_job_log(job.id, f"[{i + 1}/{total}] {prod_name}: {e}")
                failed_pids.append(pid)
            # OOM 방지: 50건마다 gc + malloc_trim으로 RSS 회수
            if (i + 1) % 50 == 0:
                _force_free_memory()
                logger.info(f"[잡워커] 메모리 회수 ({i + 1}/{total}건)")
            # 잡 progress는 매 건마다 업데이트 (재시작 시 재처리 최소화)
            if True:
                try:
                    await repo.update_progress(job.id, i + 1, total)
                    # 중간 카운트 저장 — 이어하기 시 복원용
                    _job = await repo.get_async(job.id)
                    if _job:
                        _job.result = {
                            "success": success_count,
                            "skipped": skip_count,
                            "failed": fail_count,
                        }
                    await session.commit()
                except Exception as pg_err:
                    logger.error(
                        f"[잡워커] progress 업데이트 실패: {job.id} — {pg_err}"
                    )
                    _add_job_log(
                        job.id,
                        f"[{i + 1}/{total}] DB 세션 오류 — 다음 건 계속 진행",
                    )
                    try:
                        await session.rollback()
                    except Exception:
                        pass

        # 2차 재시도 — 실패 상품만 (건별 독립 세션)
        retry_success = 0
        if failed_pids:
            _add_job_log(job.id, f"재시도 시작 — 실패 {len(failed_pids)}건")
            await asyncio.sleep(3)  # 세마포어 해제 대기
            for ri, pid in enumerate(failed_pids):
                from backend.domain.samba.emergency import is_emergency_stopped

                if is_emergency_stopped() or await repo.is_cancelled(job.id):
                    break
                try:
                    async with get_write_session() as retry_session:
                        retry_cp = SambaCollectedProductRepository(retry_session)
                        prod = await retry_cp.get_async(pid)
                        site_pid = prod.site_product_id if prod else ""
                        prod_name = prod.name[:30] if prod and prod.name else pid[-8:]
                        if site_pid:
                            prod_name = f"{prod_name} ({site_pid})"
                        retry_svc = SambaShipmentService(
                            SambaShipmentRepository(retry_session), retry_session
                        )
                        prev_fail = fail_count
                        result = await retry_svc.start_update(
                            [pid],
                            update_items,
                            target_account_ids,
                            skip_unchanged=skip_unchanged,
                        )
                        r2 = (result.get("results", []) or [{}])[0]
                        tx2 = r2.get("transmit_result", {})
                        any_ok = any(s == "success" for s in tx2.values())
                        if any_ok:
                            retry_success += 1
                            success_count += 1
                            fail_count = prev_fail - 1
                            _add_job_log(
                                job.id,
                                f"[재시도 {ri + 1}/{len(failed_pids)}] {prod_name}: 복구",
                            )
                        else:
                            _add_job_log(
                                job.id,
                                f"[재시도 {ri + 1}/{len(failed_pids)}] {prod_name}: 재실패",
                            )
                        await retry_session.commit()
                except Exception as e:
                    _add_job_log(
                        job.id, f"[재시도 {ri + 1}/{len(failed_pids)}] {prod_name}: {e}"
                    )
            if retry_success > 0:
                _add_job_log(
                    job.id, f"재시도 완료 — {retry_success}/{len(failed_pids)}건 복구"
                )

        final_fail = fail_count
        _add_job_log(
            job.id,
            f"전송 완료 — 성공 {success_count}건, 스킵 {skip_count}건, 실패 {final_fail}건",
        )
        await repo.complete_job(
            job.id,
            {"success": success_count, "skipped": skip_count, "failed": final_fail},
        )
        logger.info(
            f"[잡워커] 전송 완료: {job.id} (성공 {success_count}, 스킵 {skip_count}, 실패 {final_fail}/{total}건)"
        )

    async def _run_collect(self, job, repo, session):
        """수집 잡 실행 — collector_collection의 _stream_musinsa 로직 이식."""
        from urllib.parse import urlparse, parse_qs
        from sqlmodel import select, func as _func
        from backend.domain.samba.collector.model import SambaSearchFilter
        from backend.domain.samba.collector.model import (
            SambaCollectedProduct as CPModel,
        )
        from backend.domain.samba.proxy.musinsa import MusinsaClient, RateLimitError
        from backend.domain.samba.forbidden.model import SambaSettings
        from backend.api.v1.routers.samba.collector_common import _build_product_data
        from backend.domain.samba.collector.refresher import (
            _site_intervals,
            _site_consecutive_errors,
            get_interval_key,
        )

        _ik = get_interval_key("MUSINSA", "collect")  # 수집 전용 인터벌 키

        payload = job.payload or {}
        filter_id = payload.get("filter_id")
        if not filter_id:
            await repo.fail_job(job.id, "filter_id 없음")
            return

        # 필터 조회
        sf = await session.get(SambaSearchFilter, filter_id)
        if not sf:
            await repo.fail_job(job.id, f"필터 없음: {filter_id}")
            return

        site = sf.source_site

        # 직접 API 소싱처 (서버 HTTP)
        DIRECT_API_SITES = {"FashionPlus", "Nike", "Adidas", "LOTTEON"}
        # 확장앱 기반 소싱처 (소싱큐)
        EXTENSION_SITES = {
            "ABCmart",
            "GrandStage",
            "REXMONDE",
            "GSShop",
            "ElandMall",
            "SSF",
            "SSG",
        }

        if site in DIRECT_API_SITES:
            await self._collect_direct_api(job, sf, session, repo)
            return

        if site in EXTENSION_SITES:
            await self._collect_direct_api(job, sf, session, repo)
            return

        if site != "MUSINSA":
            await repo.fail_job(job.id, f"미지원 소싱처: {site}")
            return

        # 쿠키 로드
        result = await session.execute(
            select(SambaSettings).where(SambaSettings.key == "musinsa_cookie")
        )
        row = result.scalar_one_or_none()
        cookie = (row.value if row and row.value else "") or ""
        if not cookie:
            await repo.fail_job(job.id, "무신사 로그인(쿠키) 필요")
            return

        # 수집용 프록시 적용
        from backend.core.config import settings as _settings

        _collect_proxy = _settings.collect_proxy_url or None
        client = MusinsaClient(cookie=cookie, proxy_url=_collect_proxy)
        if _collect_proxy:
            logger.info(
                f"[잡워커] 수집 프록시: {_collect_proxy.split('@')[-1] if '@' in _collect_proxy else 'on'}"
            )

        # 키워드/옵션 추출
        keyword_or_url = sf.keyword or ""
        keyword = keyword_or_url
        _exclude_preorder = False
        _exclude_boutique = False
        _use_max_discount = False

        _brand_filter = ""
        _min_price = None
        _max_price = None
        _gf_filter = "A"
        _category_filter = ""

        try:
            parsed = urlparse(keyword_or_url)
            if parsed.scheme:
                qs = parse_qs(parsed.query)
                keyword = qs.get("keyword", [keyword])[0]
                _exclude_preorder = qs.get("excludePreorder", [""])[0] == "1"
                _exclude_boutique = qs.get("excludeBoutique", [""])[0] == "1"
                _use_max_discount = qs.get("maxDiscount", [""])[0] == "1"
                _brand_filter = qs.get("brand", [""])[0]
                _min_price_raw = qs.get("minPrice", [""])[0]
                _max_price_raw = qs.get("maxPrice", [""])[0]
                _gf_filter = qs.get("gf", ["A"])[0]
                _category_filter = qs.get("category", [""])[0]
                _min_price = int(_min_price_raw) if _min_price_raw.isdigit() else None
                _max_price = int(_max_price_raw) if _max_price_raw.isdigit() else None
        except Exception:
            pass

        # 기존 수집 수 확인
        requested_count = sf.requested_count or 100
        count_stmt = select(_func.count()).where(CPModel.search_filter_id == filter_id)
        existing_count = (await session.execute(count_stmt)).scalar() or 0
        remaining = max(0, requested_count - existing_count)

        if remaining <= 0:
            await repo.complete_job(
                job.id,
                {
                    "saved": 0,
                    "message": f"이미 {existing_count}개 수집됨 (요청: {requested_count}개)",
                },
            )
            return

        await repo.update_progress(job.id, existing_count, requested_count)

        # 수집 루프
        total_saved = 0
        total_skipped = 0
        search_page = 1
        empty_pages = 0  # 연속 신규 0건 페이지 카운터 (잡 간 오염 방지용 로컬 변수)
        max_pages = 100  # API totalPages 기반으로 동적 조정 (초기값)

        while total_saved < remaining and search_page <= max_pages:
            # 취소 확인 (DB에서 상태 재조회)
            from backend.domain.samba.job.model import SambaJob as _SJ

            _job_check = await session.get(_SJ, job.id)
            if _job_check and _job_check.status == JobStatus.FAILED:
                logger.info(f"[잡워커] 수집 취소됨: {job.id}")
                return

            # 검색
            try:
                data = await client.search_products(
                    keyword=keyword,
                    page=search_page,
                    size=100,
                    category=_category_filter,
                    brand=_brand_filter,
                    min_price=_min_price,
                    max_price=_max_price,
                    gf=_gf_filter,
                )
                search_items = data.get("data", [])
                # 첫 페이지에서 totalPages로 최대 페이지 동적 설정
                if search_page == 1:
                    api_total_pages = data.get("totalPages", 0)
                    api_total_count = data.get("totalCount", 0)
                    if api_total_pages > 0:
                        max_pages = api_total_pages
                    else:
                        logger.warning(
                            f"[잡워커] totalPages={api_total_pages}, totalCount={api_total_count} → 초기값({max_pages}) 유지"
                        )
                    logger.info(
                        f"[잡워커] API 총 {api_total_count}건, {api_total_pages}페이지 → max_pages={max_pages}"
                    )
                logger.info(
                    f"[잡워커] 검색 p{search_page}: {len(search_items)}건 (kw={keyword}, brand={_brand_filter})"
                )
                if not search_items:
                    break
                await asyncio.sleep(_site_intervals.get(_ik, 0))
            except Exception as e:
                logger.error(f"[잡워커] 검색 실패: {e}")
                break

            # 중복 필터링 (현재 필터 기준 — 다른 그룹과 독립적으로 수집)
            candidate_ids = [
                str(item.get("siteProductId", item.get("goodsNo", "")))
                for item in search_items
            ]
            existing_result = await session.execute(
                select(CPModel.site_product_id).where(
                    CPModel.search_filter_id == filter_id,
                    CPModel.site_product_id.in_(candidate_ids),
                )
            )
            existing_ids = {row[0] for row in existing_result.all()}

            targets = []
            for item in search_items:
                if total_saved + len(targets) >= remaining:
                    break
                site_pid = str(item.get("siteProductId", item.get("goodsNo", "")))
                if site_pid in existing_ids:
                    continue
                # 품절 판단은 상세 수집 단계에서 정확하게 수행 (검색 API의 isSoldOut은 부정확)
                targets.append(site_pid)

            logger.info(
                f"[잡워커] 중복={len(existing_ids)}, 타겟={len(targets)}, 스킵={total_skipped}"
            )
            if not targets:
                # 연속 5페이지 신규 0건이면 조기 종료
                empty_pages += 1
                if empty_pages >= 5:
                    logger.info(
                        f"[잡워커] 연속 {empty_pages}페이지 신규 0건 → 조기 종료"
                    )
                    break
                search_page += 1
                continue
            empty_pages = 0  # 신규 상품 발견 시 카운터 리셋

            # 상세 수집 (병렬 — SITE_CONCURRENCY + 공유 HTTP 클라이언트)
            from backend.domain.samba.collector.refresher import SITE_CONCURRENCY
            import httpx as _httpx

            _collect_sem = asyncio.Semaphore(SITE_CONCURRENCY.get("MUSINSA", 5))
            _collect_results: list[dict | None] = []
            _rate_limited = False
            _shared_http = _httpx.AsyncClient(timeout=_httpx.Timeout(15, connect=5.0))

            async def _fetch_detail(goods_no: str) -> dict | None:
                nonlocal total_skipped, _rate_limited
                if _rate_limited:
                    return None
                async with _collect_sem:
                    try:
                        detail = await client.get_goods_detail(
                            goods_no, _shared_client=_shared_http
                        )
                        if not detail or not detail.get("name"):
                            return None
                        if detail.get("saleStatus") == "sold_out" or detail.get(
                            "isOutOfStock"
                        ):
                            total_skipped += 1
                            return None
                        if _exclude_preorder and detail.get("saleStatus") == "preorder":
                            total_skipped += 1
                            return None
                        if _exclude_boutique and detail.get("isBoutique"):
                            total_skipped += 1
                            return None
                        return {"goods_no": goods_no, "detail": detail}
                    except RateLimitError as rle:
                        current = _site_intervals.get(_ik, 1.0)
                        _site_intervals[_ik] = min(30.0, current * 2)
                        _site_consecutive_errors[_ik] = (
                            _site_consecutive_errors.get("MUSINSA", 0) + 1
                        )
                        if _site_consecutive_errors[_ik] >= 5:
                            _rate_limited = True
                        if rle.retry_after > 0:
                            await asyncio.sleep(rle.retry_after)
                        return None
                    except Exception as e:
                        logger.warning(f"[잡워커] 수집 실패 {goods_no}: {e}")
                        return None

            _collect_results = await asyncio.gather(
                *[_fetch_detail(gn) for gn in targets]
            )
            await _shared_http.aclose()

            if _rate_limited:
                await repo.fail_job(job.id, "소싱처 차단 (연속 rate limit)")
                return

            # 수집된 상세 순차 저장 (DB 쓰기는 순차)
            from backend.api.v1.routers.samba.collector_common import _get_services

            svc = _get_services(session)
            for item in _collect_results:
                if item is None:
                    continue
                goods_no = item["goods_no"]
                detail = item["detail"]

                if _use_max_discount:
                    _raw_cost = detail.get("bestBenefitPrice")
                    new_cost = (
                        _raw_cost
                        if (_raw_cost is not None and _raw_cost > 0)
                        else (detail.get("salePrice") or 0)
                    )
                else:
                    new_cost = detail.get("salePrice") or 0

                raw_cat = detail.get("category", "") or ""
                cat_parts = (
                    [c.strip() for c in raw_cat.split(">") if c.strip()]
                    if raw_cat
                    else []
                )
                _sale_price = detail.get("salePrice", 0)
                _original_price = detail.get("originalPrice", 0)

                raw_detail_html = detail.get("detailHtml", "")
                if not raw_detail_html:
                    detail_imgs = detail.get("detailImages") or []
                    if detail_imgs:
                        raw_detail_html = "\n".join(
                            f'<div style="text-align:center;"><img src="{img}" style="max-width:860px;width:100%;" /></div>'
                            for img in detail_imgs
                        )

                product_data = _build_product_data(
                    detail,
                    goods_no,
                    filter_id,
                    "MUSINSA",
                    new_cost,
                    _sale_price,
                    _original_price,
                    raw_cat,
                    cat_parts,
                    raw_detail_html,
                )
                await svc.create_collected_product(product_data)
                total_saved += 1
                await repo.update_progress(
                    job.id, existing_count + total_saved, requested_count
                )

                if total_saved >= remaining:
                    break

            search_page += 1

        # 수집 완료 → last_collected_at 갱신 + 요청수를 실제 수집수로 보정
        from sqlalchemy import update as _sa_upd

        _actual = (
            await session.execute(
                select(_func.count()).where(CPModel.search_filter_id == filter_id)
            )
        ).scalar() or 0
        _upd_vals: dict = {"last_collected_at": datetime.now(UTC)}
        # requested_count는 실제 수집수가 더 클 때만 갱신 (축소 방지)
        if _actual > requested_count:
            _upd_vals["requested_count"] = _actual
            logger.info(f"[잡워커] requested_count 갱신: {requested_count} → {_actual}")
        elif _actual < requested_count:
            logger.info(
                f"[잡워커] 실제 {_actual}건 < 요청 {requested_count}건 (축소 방지로 유지)"
            )
        await session.execute(
            _sa_upd(SambaSearchFilter)
            .where(SambaSearchFilter.id == filter_id)
            .values(**_upd_vals)
        )

        # 정책 자동 적용
        policy_msg = ""
        if sf.applied_policy_id and total_saved > 0:
            try:
                from backend.domain.samba.policy.repository import SambaPolicyRepository
                from backend.api.v1.routers.samba.collector_common import _get_services

                svc = _get_services(session)
                policy_repo = SambaPolicyRepository(session)
                policy = await policy_repo.get_async(sf.applied_policy_id)
                policy_data = None
                if policy and policy.pricing:
                    pr = policy.pricing if isinstance(policy.pricing, dict) else {}
                    policy_data = {
                        "margin_rate": pr.get("marginRate", 15),
                        "shipping_cost": pr.get("shippingCost", 0),
                        "extra_charge": pr.get("extraCharge", 0),
                        "use_range_margin": pr.get("useRangeMargin", False),
                        "range_margins": pr.get("rangeMargins", []),
                    }
                count = await svc.apply_policy_to_filter_products(
                    filter_id, sf.applied_policy_id, policy_data
                )
                policy_msg = f"정책 적용: {count}개"
            except Exception as e:
                logger.error(f"[잡워커] 정책 전파 실패: {e}")

        await repo.complete_job(
            job.id,
            {
                "saved": total_saved,
                "skipped": total_skipped,
                "policy": policy_msg,
            },
        )
        logger.info(f"[잡워커] 수집 완료: {job.id} ({total_saved}건)")

    async def _collect_direct_api(self, job, sf, session, repo):
        """FashionPlus/Nike/Adidas 등 직접 API 소싱처 수집."""
        from sqlalchemy import func as _func, select
        from backend.domain.samba.collector.model import (
            SambaCollectedProduct as CPModel,
        )
        from backend.api.v1.routers.samba.collector_common import (
            _get_services,
            generate_group_key,
        )

        site = sf.source_site
        filter_id = sf.id
        keyword = sf.keyword or ""
        requested_count = sf.requested_count or 100

        # URL에서 키워드/필터 추출
        _search_kwargs: dict = {}
        try:
            from urllib.parse import urlparse, parse_qs

            parsed = urlparse(keyword)
            if parsed.scheme:
                qs = parse_qs(parsed.query)
                # 소싱처별 키워드 파라미터: LOTTEON=q, FashionPlus=searchWord
                keyword = qs.get(
                    "q", qs.get("keyword", qs.get("searchWord", [keyword]))
                )[0]
                # 패션플러스 필터 파라미터
                for k in (
                    "category1Id",
                    "category2Id",
                    "category3Id",
                    "sort",
                    "minPrice",
                    "maxPrice",
                ):
                    v = qs.get(k, [""])[0]
                    if v:
                        _search_kwargs[k] = v
                # brands 파라미터
                brand_ids = qs.get("brands[][id]", [])
                brand_names = qs.get("brands[][name]", [])
                if brand_ids:
                    _search_kwargs["brand_id"] = brand_ids[0]
                if brand_names:
                    _search_kwargs["brand_name"] = brand_names[0]
                # skipDetail 옵션
                if qs.get("skipDetail", [""])[0] == "1":
                    _search_kwargs["_skip_detail"] = True
        except Exception:
            pass

        # 기존 수집 수 확인
        count_stmt = select(_func.count()).where(CPModel.search_filter_id == filter_id)
        existing_count = (await session.execute(count_stmt)).scalar() or 0
        remaining = max(0, requested_count - existing_count)
        if remaining <= 0:
            await repo.complete_job(
                job.id, {"saved": 0, "message": f"이미 {existing_count}개 수집됨"}
            )
            return

        # 클라이언트 생성 — 직접 API 소싱처
        client = None
        if site == "FashionPlus":
            from backend.domain.samba.proxy.fashionplus import FashionPlusClient

            client = FashionPlusClient()
        elif site == "Nike":
            from backend.domain.samba.proxy.nike import NikeClient

            client = NikeClient()
        elif site == "Adidas":
            from backend.domain.samba.proxy.adidas import AdidasClient

            client = AdidasClient()
        elif site == "LOTTEON":
            from backend.domain.samba.proxy.lotteon_sourcing import (
                LotteonSourcingClient,
            )

            client = LotteonSourcingClient()

        # 확장앱 소싱큐 기반 사이트 — 소싱큐로 검색 요청
        if not client:
            from backend.domain.samba.proxy.sourcing_queue import (
                SourcingQueue,
                SITE_SEARCH_URLS,
            )

            if site not in SITE_SEARCH_URLS:
                await repo.fail_job(job.id, f"미지원 소싱처: {site}")
                return
            try:
                _req_id, _future = SourcingQueue.add_search_job(site, keyword)
                ext_result = await asyncio.wait_for(_future, timeout=60)
                items_list = ext_result.get("products", [])
                logger.info(
                    f"[잡워커] {site} 확장앱 검색 '{keyword}' → {len(items_list)}건"
                )
            except asyncio.TimeoutError:
                SourcingQueue.resolvers.pop(_req_id, None)
                await repo.fail_job(
                    job.id, "확장앱 응답 타임아웃. 확장앱이 실행 중인지 확인하세요."
                )
                return
            except Exception as e:
                await repo.fail_job(job.id, f"확장앱 검색 실패: {e}")
                return
            # 확장앱 결과는 검색 API와 동일 포맷으로 처리 (아래 중복필터+저장 로직 공유)
            result = {"products": items_list, "total": len(items_list)}

        else:
            # 직접 API 검색
            # LOTTEON: brands 파라미터가 있으면 각 브랜드명을 키워드로 개별 검색해서 합침
            # (qapi 검색은 키워드 관련도 기반이라 단일 키워드로 검색하면 서브브랜드가 누락됨)
            _per_brand_keywords: list[str] = []
            if site == "LOTTEON":
                try:
                    parsed_kw = urlparse(sf.keyword or "")
                    if parsed_kw.scheme:
                        _qs_kw = parse_qs(parsed_kw.query)
                        _bp = _qs_kw.get("brands", [""])[0]
                        if _bp:
                            _per_brand_keywords = [
                                b.strip() for b in _bp.split(",") if b.strip()
                            ]
                except Exception:
                    pass

            try:
                if _per_brand_keywords:
                    items_list = []
                    seen_pids: set[str] = set()
                    per_max = max(remaining * 2, 100)
                    for _kw in _per_brand_keywords:
                        try:
                            _r = await client.search(
                                _kw, max_count=per_max, **_search_kwargs
                            )
                            _items = _r.get("products", [])
                            for _it in _items:
                                _pid = str(_it.get("site_product_id", ""))
                                if _pid and _pid in seen_pids:
                                    continue
                                if _pid:
                                    seen_pids.add(_pid)
                                items_list.append(_it)
                            logger.info(
                                f"[잡워커] LOTTEON 브랜드별 검색 '{_kw}' → {len(_items)}건"
                            )
                        except Exception as _be:
                            logger.warning(
                                f"[잡워커] LOTTEON 브랜드 '{_kw}' 검색 실패: {_be}"
                            )
                    result = {"products": items_list, "total": len(items_list)}
                    logger.info(
                        f"[잡워커] LOTTEON 브랜드별 검색 합계 → {len(items_list)}건"
                    )
                else:
                    result = await client.search(
                        keyword, max_count=max(remaining * 2, 100), **_search_kwargs
                    )
                    items_list = result.get("products", [])
                    logger.info(
                        f"[잡워커] {site} 검색 '{keyword}' → {len(items_list)}건"
                    )
            except Exception as e:
                await repo.fail_job(job.id, f"검색 실패: {e}")
                return

        # LOTTEON: category_filter(BC코드, 콤마 구분)로 검색 결과 사후 필터링
        if site == "LOTTEON" and sf.category_filter:
            bc_set = set(sf.category_filter.split(","))
            before = len(items_list)
            items_list = [
                item for item in items_list if (item.get("scat_no") or "") in bc_set
            ]
            logger.info(
                f"[잡워커] LOTTEON BC코드 필터 {sf.category_filter}: {before}→{len(items_list)}건"
            )

        # LOTTEON: 선택된 브랜드 목록으로 정확 일치 필터링
        # URL 파라미터 brands=나이키,나이키 키즈 형태 (콤마 구분)
        # brands 파라미터 없으면 keyword 단일 브랜드로 사용 (하위 호환)
        if site == "LOTTEON":
            from backend.domain.samba.proxy.lotteon_sourcing import _filter_by_brands

            _selected_brands: list[str] = []
            try:
                parsed2 = urlparse(sf.keyword or "")
                if parsed2.scheme:
                    _qs2 = parse_qs(parsed2.query)
                    _brands_param = _qs2.get("brands", [""])[0]
                    if _brands_param:
                        _selected_brands = [
                            b.strip() for b in _brands_param.split(",") if b.strip()
                        ]
            except Exception:
                pass

            if not _selected_brands and keyword:
                _selected_brands = [keyword]

            # 브랜드별로 직접 검색했다면 brand 정확일치 필터를 건너뛴다.
            # (검색 결과의 brand 필드가 키워드와 다를 수 있으나 키워드 검색 결과를 신뢰)
            if locals().get("_per_brand_keywords"):
                _selected_brands = []

            if _selected_brands:
                before = len(items_list)
                items_list = _filter_by_brands(items_list, _selected_brands)
                if before != len(items_list):
                    logger.info(
                        f"[잡워커] LOTTEON 브랜드 필터 {_selected_brands}: {before}→{len(items_list)}건"
                    )

        await repo.update_progress(job.id, 0, remaining)

        # 카테고리 매핑 (패션플러스)
        _category1_name = ""
        if site == "FashionPlus" and _search_kwargs.get("category1Id"):
            from backend.domain.samba.proxy.fashionplus import _CATEGORY_MAP

            _category1_name = _CATEGORY_MAP.get(_search_kwargs["category1Id"], "")

        # 중복 필터링
        candidate_ids = [
            str(item.get("site_product_id", ""))
            for item in items_list
            if item.get("site_product_id")
        ]
        existing_ids: set[str] = set()
        if candidate_ids:
            existing_result = await session.execute(
                select(CPModel.site_product_id).where(
                    CPModel.source_site == site,
                    CPModel.site_product_id.in_(candidate_ids),
                )
            )
            existing_ids = {row[0] for row in existing_result.all()}

        svc = _get_services(session)
        total_saved = 0

        # LOTTEON: 저장 전 10건 병렬로 상세 정보 선취합 (1단계 통합 수집)
        _lotteon_details: dict[str, dict[str, Any]] = {}
        if site == "LOTTEON" and client:
            # 중복 제외한 신규 상품만 상세 조회
            new_items = [
                it
                for it in items_list
                if str(it.get("site_product_id", "")) not in existing_ids
            ][:remaining]
            if new_items:
                logger.info(
                    f"[잡워커] LOTTEON 상세 선취합 시작: {len(new_items)}건 (10건 병렬)"
                )
                BATCH_SIZE = 10
                for batch_start in range(0, len(new_items), BATCH_SIZE):
                    batch = new_items[batch_start : batch_start + BATCH_SIZE]
                    details = await asyncio.gather(
                        *(
                            client.get_detail(str(it.get("site_product_id", "")))
                            for it in batch
                        ),
                        return_exceptions=True,
                    )
                    for it, det in zip(batch, details):
                        pid = str(it.get("site_product_id", ""))
                        if isinstance(det, Exception):
                            logger.warning(
                                f"[잡워커] LOTTEON 상세 선취합 실패 {pid}: {det}"
                            )
                            continue
                        if det:
                            _lotteon_details[pid] = det
                    done = min(batch_start + BATCH_SIZE, len(new_items))
                    logger.info(
                        f"[잡워커] LOTTEON 상세 선취합 [{done}/{len(new_items)}]"
                    )
                    await asyncio.sleep(0.3)
                logger.info(
                    f"[잡워커] LOTTEON 상세 선취합 완료: {len(_lotteon_details)}/{len(new_items)}건 성공"
                )

        for item in items_list:
            if total_saved >= remaining:
                break

            # 취소 확인 (DB에서 상태 재조회)
            from backend.domain.samba.job.model import SambaJob as _SJ2

            _job_chk = await session.get(_SJ2, job.id)
            if _job_chk and _job_chk.status == JobStatus.FAILED:
                logger.info(f"[잡워커] {site} 수집 취소됨: {job.id}")
                return

            p_id = str(item.get("site_product_id", ""))
            if p_id in existing_ids:
                continue

            p_name = item.get("name", "")
            sale_price = int(item.get("sale_price", 0))
            original_price = int(item.get("original_price", 0)) or sale_price
            if not p_name and not sale_price:
                continue

            # LOTTEON: search 결과의 scat_no로 카테고리 미리 매핑
            _lotteon_cat = ""
            _lotteon_cat1 = ""
            _lotteon_cat2 = ""
            _lotteon_cat3 = ""
            _lotteon_scat_no = ""
            if site == "LOTTEON":
                from backend.domain.samba.proxy.lotteon_sourcing import (
                    _LOTTEON_SCAT_NAMES,
                )

                _lotteon_scat_no = item.get("scat_no") or item.get("scatNo") or ""
                if _lotteon_scat_no:
                    _cat_name = _LOTTEON_SCAT_NAMES.get(_lotteon_scat_no, "")
                    if _cat_name:
                        _lotteon_cat = _cat_name
                        _parts = _cat_name.split(" > ")
                        _lotteon_cat1 = _parts[0] if len(_parts) > 0 else ""
                        _lotteon_cat2 = _parts[1] if len(_parts) > 1 else ""
                        _lotteon_cat3 = _parts[2] if len(_parts) > 2 else ""

            # 상세 페이지에서 추가 이미지/고시정보 보충
            detail = {}
            # LOTTEON: 선취합된 상세 데이터 사용
            if site == "LOTTEON" and p_id in _lotteon_details:
                detail = _lotteon_details[p_id]
            _skip_detail = _search_kwargs.get("_skip_detail", False)
            if not _skip_detail and not detail:
                # 서버 HTTP 상세 조회 (빠르고 안정적)
                if hasattr(client, "get_detail"):
                    try:
                        detail = await client.get_detail(p_id)
                        await asyncio.sleep(0.3)
                    except Exception as e:
                        logger.warning(f"[잡워커] {site} 서버 상세 실패 {p_id}: {e}")

            # 이미지: 확장앱 결과와 검색 API 중 더 많은 쪽 사용
            _detail_imgs = detail.get("images") or []
            _search_imgs = item.get("images", [])
            images = (
                _detail_imgs if len(_detail_imgs) > len(_search_imgs) else _search_imgs
            )
            cost = int(item.get("cost", 0)) or sale_price
            # 배송비 원가 가산 (무료배송 아닌 경우)
            _sourcing_ship_fee = 0
            if not item.get("free_shipping", False):
                _sourcing_ship_fee = int(detail.get("shipping_fee", 3000))
                cost += _sourcing_ship_fee
            _style_code = detail.get("style_code") or item.get("style_code", "")
            product_data = {
                "source_site": site,
                "search_filter_id": filter_id,
                "site_product_id": p_id,
                "source_url": item.get("source_url", "")
                or detail.get("source_url", ""),
                "name": p_name,
                "brand": item.get("brand", ""),
                "original_price": original_price,
                "sale_price": sale_price,
                "cost": cost,
                "images": images,
                "options": detail.get("options") or item.get("options", []),
                "category": detail.get("category")
                or _lotteon_cat
                or item.get("category", "")
                or _category1_name,
                "category1": detail.get("category1")
                or _lotteon_cat1
                or item.get("category1", ""),
                "category2": detail.get("category2")
                or _lotteon_cat2
                or item.get("category2", ""),
                "category3": detail.get("category3")
                or _lotteon_cat3
                or item.get("category3", ""),
                "detail_html": detail.get("detail_html") or item.get("detail_html", ""),
                "detail_images": detail.get("detail_images")
                if len(detail.get("detail_images") or []) > len(images)
                else images,
                "material": detail.get("material", ""),
                "color": detail.get("color", ""),
                "manufacturer": detail.get("manufacturer") or item.get("brand", ""),
                "origin": detail.get("origin", ""),
                "care_instructions": detail.get("care_instructions", ""),
                "quality_guarantee": detail.get("quality_guarantee", ""),
                "sourcing_shipping_fee": _sourcing_ship_fee,
                "style_code": _style_code,
                "status": "collected",
                "group_key": generate_group_key(
                    brand=item.get("brand", ""),
                    similar_no=None,
                    style_code=_style_code,
                    name=p_name,
                )
                or f"fp_{site.lower()}_{p_id}",
                "price_history": [
                    {
                        "date": datetime.now(UTC).isoformat(),
                        "sale_price": sale_price,
                        "original_price": original_price,
                        "cost": cost,
                        "options": detail.get("options") or item.get("options", []),
                    }
                ],
            }
            try:
                await svc.create_collected_product(product_data)
                total_saved += 1
                await repo.update_progress(
                    job.id, existing_count + total_saved, requested_count
                )
            except Exception as e:
                logger.warning(f"[잡워커] {site} 저장 실패 {p_id}: {e}")

        # last_collected_at 갱신 + 요청수를 실제 수집수로 보정 (카테고리 중복 제거)
        from sqlalchemy import update as sa_update

        actual_count = (
            await session.execute(
                select(_func.count()).where(CPModel.search_filter_id == filter_id)
            )
        ).scalar() or 0
        update_vals: dict = {"last_collected_at": datetime.now(UTC)}
        if actual_count > 0:
            update_vals["requested_count"] = actual_count
        from backend.domain.samba.collector.model import SambaSearchFilter as _SF

        await session.execute(
            sa_update(_SF).where(_SF.id == filter_id).values(**update_vals)
        )

        # 정책 자동 적용
        policy_msg = ""
        if sf.applied_policy_id and total_saved > 0:
            try:
                from backend.domain.samba.policy.repository import SambaPolicyRepository

                policy_repo = SambaPolicyRepository(session)
                policy = await policy_repo.get_async(sf.applied_policy_id)
                policy_data = None
                if policy and policy.pricing:
                    pr = policy.pricing if isinstance(policy.pricing, dict) else {}
                    policy_data = {
                        "margin_rate": pr.get("marginRate", 15),
                        "shipping_cost": pr.get("shippingCost", 0),
                        "extra_charge": pr.get("extraCharge", 0),
                        "use_range_margin": pr.get("useRangeMargin", False),
                        "range_margins": pr.get("rangeMargins", []),
                    }
                count = await svc.apply_policy_to_filter_products(
                    filter_id, sf.applied_policy_id, policy_data
                )
                policy_msg = f", 정책 적용: {count}개"
            except Exception as e:
                logger.error(f"[잡워커] {site} 정책 전파 실패: {e}")

        await repo.complete_job(job.id, {"saved": total_saved})
        logger.info(
            f"[잡워커] {site} 수집 완료: {job.id} ({total_saved}건{policy_msg})"
        )

        # LOTTEON: 수집 완료 후 상세 보강 (품번/제조국/성별/시즌/색상/재질)
        # 10건 병렬로 get_detail 호출하여 속도 개선
        # LOTTEON: 선취합 실패분만 보강 (폴백)
        _enrich_needed = total_saved - len(_lotteon_details) if site == "LOTTEON" else 0
        if site == "LOTTEON" and _enrich_needed > 0 and client:
            logger.info(f"[잡워커] LOTTEON 보강(폴백): 선취합 실패 {_enrich_needed}건")
            enrich_stmt = select(CPModel).where(
                CPModel.search_filter_id == filter_id,
                CPModel.source_site == "LOTTEON",
                CPModel.brand == None,  # noqa: E711 — 선취합 안 된 상품
            )
            products_to_enrich = (await session.execute(enrich_stmt)).scalars().all()

            BATCH_SIZE = 10
            enriched = 0
            total = len(products_to_enrich)

            for batch_start in range(0, total, BATCH_SIZE):
                batch = products_to_enrich[batch_start : batch_start + BATCH_SIZE]
                # 10건 동시 get_detail 호출
                details = await asyncio.gather(
                    *(client.get_detail(p.site_product_id) for p in batch),
                    return_exceptions=True,
                )
                for prod, detail in zip(batch, details):
                    if isinstance(detail, Exception):
                        logger.warning(
                            f"[잡워커] LOTTEON 상세 보강 실패 {prod.site_product_id}: {detail}"
                        )
                        continue
                    if not detail:
                        continue
                    changed = False
                    for field in (
                        "material",
                        "color",
                        "origin",
                        "sex",
                        "season",
                        "care_instructions",
                        "quality_guarantee",
                    ):
                        val = detail.get(field, "")
                        if val and not getattr(prod, field, ""):
                            setattr(prod, field, val)
                            changed = True
                    # 브랜드
                    brd = detail.get("brand", "")
                    if brd and not (prod.brand or ""):
                        prod.brand = brd
                        changed = True
                    # 품번 (style_code)
                    sc = detail.get("style_code") or detail.get("styleCode") or ""
                    if sc and not (prod.style_code or ""):
                        prod.style_code = sc
                        changed = True
                    # 제조사
                    mfr = detail.get("manufacturer", "")
                    if mfr and not (prod.manufacturer or ""):
                        prod.manufacturer = mfr
                        changed = True
                    # 카테고리
                    cat = detail.get("category", "")
                    if cat and not (prod.category or "" == "-"):
                        prod.category = cat
                        changed = True
                    # 이미지 보강
                    d_imgs = detail.get("images") or []
                    if len(d_imgs) > len(prod.images or []):
                        prod.images = d_imgs
                        changed = True
                    d_detail_imgs = detail.get("detail_images") or []
                    if d_detail_imgs and not (prod.detail_images or []):
                        prod.detail_images = d_detail_imgs
                        changed = True
                    # 옵션 보강
                    d_opts = detail.get("options") or []
                    if d_opts and not (prod.options or []):
                        prod.options = d_opts
                        changed = True
                    if changed:
                        session.add(prod)
                        enriched += 1
                await session.commit()
                done = min(batch_start + BATCH_SIZE, total)
                logger.info(
                    f"[잡워커] LOTTEON 상세 보강 [{done}/{total}] ({enriched}건 업데이트)"
                )
                await asyncio.sleep(0.3)

            logger.info(
                f"[잡워커] LOTTEON 상세 보강 완료: {enriched}/{total}건 업데이트"
            )

    async def _run_stub(self, job, repo, name: str):
        """미구현 잡 타입 스텁."""
        logger.info(f"[잡워커] {name} 잡은 아직 미구현: {job.id}")
        await repo.complete_job(job.id, {"message": f"{name} 잡 미구현 — 추후 지원"})
