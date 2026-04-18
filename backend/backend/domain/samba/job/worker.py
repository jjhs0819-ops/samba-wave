"""백그라운드 잡 워커 — FastAPI lifespan에서 실행.

재시작 시 stuck running 잡 자동 복구 포함.
"""

import asyncio
import ctypes
import gc
import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

from backend.domain.samba.collector.model import generate_search_cache_id

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


# ── 수집 로그 전용 링 버퍼 (전송과 동일 방식) ──
_collect_log_buffer: deque[str] = deque(maxlen=300)
_collect_log_total: int = 0


def get_collect_logs(since_idx: int = 0) -> tuple[list[str], int]:
    """수집 로그 링 버퍼 조회 (since_idx 이후). (logs, current_idx) 반환."""
    global _collect_log_total
    buf_len = len(_collect_log_buffer)
    buf_start = _collect_log_total - buf_len
    if since_idx >= _collect_log_total:
        return [], _collect_log_total
    if since_idx <= buf_start:
        logs = list(_collect_log_buffer)
    else:
        offset = since_idx - buf_start
        logs = list(_collect_log_buffer)[offset:]
    return logs, _collect_log_total


def _add_collect_log(msg: str):
    """수집 로그를 링 버퍼에 추가."""
    global _collect_log_total
    _collect_log_buffer.append(msg)
    _collect_log_total += 1


def clear_collect_logs():
    """수집 로그 링 버퍼 초기화."""
    global _collect_log_total
    _collect_log_buffer.clear()
    _collect_log_total = 0


async def _flush_job_logs(job_id: str, logs: list[str], job_type: str) -> None:
    """잡 로그를 DB에 영속화 — 서버 재시작 후 복원용."""
    if not logs:
        return
    try:
        from sqlalchemy import text as _text
        from backend.db.orm import get_write_session

        async with get_write_session() as session:
            await session.execute(
                _text("UPDATE samba_jobs SET logs = :logs::jsonb WHERE id = :jid"),
                {"logs": json.dumps(logs, ensure_ascii=False), "jid": job_id},
            )
            await session.commit()
        logger.info(f"[잡워커] {job_type} 로그 DB 저장: {job_id} ({len(logs)}줄)")
    except Exception as le:
        logger.warning(f"[잡워커] {job_type} 로그 DB 저장 실패: {job_id} — {le}")


def get_job_logs(job_id: str, since: int = 0) -> list[str]:
    """Job 로그 조회 (since 인덱스 이후)."""
    buf = _job_logs.get(job_id)
    if not buf:
        return []
    return buf[since:]


def _add_job_log(job_id: str, msg: str, job_type: str = ""):
    """Job 로그 추가 (최대 _MAX_JOB_LOGS 유지) + 링 버퍼에도 저장."""
    # 백엔드 타임스탬프 (KST) — 프론트 폴링 시각이 아닌 실제 처리 시각 기록
    from datetime import datetime as _dt, timezone, timedelta

    msg = f"[{(_dt.now(timezone.utc) + timedelta(hours=9)).strftime('%H:%M:%S')}] {msg}"
    if job_id not in _job_logs:
        _job_logs[job_id] = []
    buf = _job_logs[job_id]
    buf.append(msg)
    if len(buf) > _MAX_JOB_LOGS:
        _job_logs[job_id] = buf[-_MAX_JOB_LOGS:]
    # 수집/전송 링 버퍼 분기
    if job_type == "collect":
        _add_collect_log(msg)
    else:
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


async def _fail_job_safe(job_id: str, error_msg: str) -> None:
    """스레드 크래시 시 안전하게 잡을 FAILED로 마킹 (RUNNING 고착 방지)."""
    from backend.db.orm import get_write_session
    from backend.domain.samba.job.repository import SambaJobRepository

    async with get_write_session() as session:
        repo = SambaJobRepository(session)
        await repo.fail_job(job_id, error_msg)
        await session.commit()
    _add_job_log(job_id, f"수집 실패: {error_msg}", job_type="collect")


def _run_collect_in_thread(worker: "JobWorker", job_id: str, payload: dict):
    """별도 스레드에서 독립 이벤트 루프로 수집 실행."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(worker._execute_collect_isolated(job_id, payload))
    except Exception as e:
        logger.error(f"[잡워커] 수집 스레드 에러: {job_id} — {e}")
        # 잡 상태를 FAILED로 업데이트 — 미처리 시 RUNNING 고착 → stuck 복구 → 무한 재시작
        try:
            loop.run_until_complete(_fail_job_safe(job_id, f"수집 스레드 에러: {e}"))
        except Exception as fe:
            logger.error(
                f"[잡워커] 수집 스레드 에러 후 잡 상태 갱신 실패: {job_id} — {fe}"
            )
    finally:
        # 스레드 전용 엔진 dispose — 풀의 TCP 커넥션을 Cloud SQL에 즉시 반납
        # 생략 시 loop.close() 만으로는 asyncpg 소켓이 GC까지 살아있어 좀비 누적 → max_connections 고갈 원인
        try:
            from backend.db.orm import _write_engine_cache, _read_engine_cache

            for _cache in (_write_engine_cache, _read_engine_cache):
                _eng = _cache.get(loop)
                if _eng is not None:
                    try:
                        loop.run_until_complete(_eng.dispose())
                    except Exception as de:
                        logger.warning(f"[잡워커] 수집 엔진 dispose 실패: {de}")
        except Exception:
            pass
        loop.close()


def _run_transmit_in_thread(worker: "JobWorker", job_id: str, payload: dict):
    """별도 스레드에서 독립 이벤트 루프로 전송 실행 — API 요청과 I/O 완전 격리."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(worker._execute_transmit_isolated(job_id, payload))
    except Exception as e:
        logger.error(f"[잡워커] 전송 스레드 에러: {job_id} — {e}")
        # 잡 상태를 FAILED로 업데이트 — 미처리 시 RUNNING 고착 방지
        _err_msg = f"전송 스레드 에러: {e}"
        try:
            from backend.db.orm import get_write_session
            from backend.domain.samba.job.repository import SambaJobRepository

            async def _fail_transmit():
                async with get_write_session() as session:
                    repo = SambaJobRepository(session)
                    await repo.fail_job(job_id, _err_msg)
                    await session.commit()

            loop.run_until_complete(_fail_transmit())
        except Exception as fe:
            logger.error(
                f"[잡워커] 전송 스레드 에러 후 잡 상태 갱신 실패: {job_id} — {fe}"
            )
    finally:
        loop.close()


class JobWorker:
    """pending 잡을 폴링하여 병렬 실행 (전송 무제한 동시)."""

    POLL_INTERVAL = 5  # 초

    STUCK_CHECK_INTERVAL = 2  # 2회 폴링마다 stuck 체크 (≒10초)
    STUCK_THRESHOLD_SEC = 1800  # 30분 이상 RUNNING 상태면 stuck 판정 (ABCmart 대량 수집 정상 소요시간 수용)

    def __init__(self):
        self._running = True
        self._shutting_down = False  # SIGTERM 수신 시 True — 전송 루프가 체크
        self._active_job_ids: set[str] = set()  # 현재 실행 중인 잡 ID 집합
        self._active_tasks: dict[
            str, asyncio.Task
        ] = {}  # job_id → Task (수집+전송 병렬용)
        # 소싱처별 동시 실행 제어 — 같은 소싱처는 순차, 다른 소싱처는 병렬
        self._active_collect_sources: set[str] = set()
        self._poll_count = 0
        # 검색 결과 캐시: {(site, keyword): (items_list, timestamp)}
        # 동일 브랜드 그룹 수집 시 전수 검색 1회만 실행
        self._search_cache: dict[tuple[str, str], tuple[list, float]] = {}

    async def start(self):
        """무한 루프: pending 잡 조회 → 전송 잡 병렬 실행 (무제한)."""
        logger.info("[잡워커] 시작 (병렬 모드: 전송 무제한 동시 실행)")
        _worker_status["alive"] = "true"
        _worker_status["started_at"] = datetime.now(UTC).isoformat()
        _worker_status["restarts"] = str(int(_worker_status.get("restarts") or 0) + 1)
        # 부팅 시 이전 프로세스의 잔류 세마포어 1회 클리어
        try:
            from backend.domain.samba.shipment.service import clear_account_semaphores

            clear_account_semaphores()
        except Exception:
            pass
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
        """stuck running 잡을 pending으로 복구 — 현재 워커가 실행 중인 잡은 제외."""
        try:
            from backend.db.orm import get_write_session
            from backend.domain.samba.job.repository import SambaJobRepository

            async with get_write_session() as session:
                repo = SambaJobRepository(session)
                recovered = await repo.recover_stuck_running(
                    exclude_ids=self._active_job_ids,
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
        2) 최대 timeout초 대기 → 모든 전송 Task 종료 확인
        3) running Job → pending으로 전환 (current 보존)
        """
        self._shutting_down = True
        self._running = False
        logger.info(
            f"[잡워커] graceful_stop — {len(self._active_job_ids)}개 잡 종료 대기"
        )

        # 모든 활성 Task가 종료될 때까지 대기
        for _ in range(timeout):
            if not self._active_tasks and not self._active_collect_sources:
                break
            await asyncio.sleep(1)

        # 모든 running transmit Job → pending 복구 (current 보존)
        # _execute_job().finally가 먼저 _active_job_ids를 비우므로
        # remaining_ids에 의존하지 않고 DB를 직접 조회한다
        try:
            from backend.db.orm import get_write_session
            from sqlalchemy import text

            async with get_write_session() as session:
                r = await session.execute(
                    text(
                        "UPDATE samba_jobs SET status = 'pending', "
                        "started_at = NULL "
                        "WHERE status = 'running' AND job_type = 'transmit'"
                    )
                )
                await session.commit()
                if r.rowcount > 0:
                    logger.info(
                        f"[잡워커] 배포 종료 — {r.rowcount}개 잡 → pending 복구"
                    )
        except Exception as e:
            logger.error(f"[잡워커] 배포 종료 잡 복구 실패: {e}")

    async def _poll_once(self) -> bool:
        """전송 잡 병렬 실행 (무제한).

        FOR UPDATE SKIP LOCKED로 원자적 잡 획득 — 멀티 worker 중복 실행 방지.
        """
        _worker_status["last_poll"] = datetime.now(UTC).isoformat()

        # 완료된 전송 Task 정리
        done_ids = [jid for jid, task in self._active_tasks.items() if task.done()]
        for jid in done_ids:
            task = self._active_tasks.pop(jid)
            self._active_job_ids.discard(jid)
            exc = task.exception()
            if exc:
                logger.error(f"[잡워커] 전송 Task 예외: {jid} — {exc}")

        from backend.db.orm import get_write_session
        from backend.domain.samba.job.repository import SambaJobRepository

        async with get_write_session() as session:
            repo = SambaJobRepository(session)
            # 현재 실행 중인 소싱처는 제외 — 같은 소싱처 순차, 다른 소싱처 병렬
            _excl_sources = set(self._active_collect_sources)
            job = await repo.claim_pending_job(exclude_sources=_excl_sources or None)
            if not job:
                return bool(self._active_tasks)

            self._active_job_ids.add(job.id)
            await session.commit()

        # 전송: asyncio.Task로 백그라운드 병렬 실행
        if job.job_type == "transmit":
            task = asyncio.create_task(
                self._execute_job(job),
                name=f"transmit-{job.id}",
            )
            self._active_tasks[job.id] = task
            logger.info(
                f"[잡워커] 전송 Task 생성: {job.id} "
                f"(동시 실행: {len(self._active_tasks)}개)"
            )
            return True

        # 수집: 소싱처별 병렬 Task (같은 소싱처는 exclude_sources로 순차 보장)
        if job.job_type == "collect":
            task = asyncio.create_task(
                self._execute_job(job),
                name=f"collect-{job.id}",
            )
            self._active_tasks[job.id] = task
            _site = (job.payload or {}).get("source_site", "?")
            logger.info(
                f"[잡워커] 수집 Task 생성: {job.id} (site={_site}, "
                f"활성 소싱처={sorted(self._active_collect_sources | {_site})})"
            )
            return True

        # 기타: 기존 방식 (동기 대기)
        await self._execute_job(job)
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
                _collect_site = (_job_payload or {}).get("source_site") or ""
                if _collect_site:
                    self._active_collect_sources.add(_collect_site)
                logger.info(
                    f"[잡워커] 수집 실행 (격리 스레드): {_job_id} site={_collect_site}"
                )
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
                    if self._shutting_down:
                        # 배포/재시작 중단 — pending으로 복구 (다음 인스턴스에서 재실행)
                        logger.info(
                            f"[잡워커] 수집 중 배포 중단 → pending 복구: {_job_id}"
                        )
                        _add_job_log(
                            _job_id,
                            "배포 중단 — 재시작 후 자동 재실행",
                            job_type="collect",
                        )
                        try:
                            async with get_write_session() as shutdown_session:
                                from sqlalchemy import text as _text

                                await shutdown_session.execute(
                                    _text(
                                        "UPDATE samba_jobs SET status='pending' WHERE id=:jid AND status='running'"
                                    ),
                                    {"jid": _job_id},
                                )
                                await shutdown_session.commit()
                        except Exception as se:
                            logger.error(f"[잡워커] 배포 중단 pending 복구 실패: {se}")
                    else:
                        # 실제 10분 타임아웃
                        logger.error(f"[잡워커] 수집 스레드 10분 타임아웃: {_job_id}")
                        _add_job_log(
                            _job_id, "수집 타임아웃 (10분)", job_type="collect"
                        )
                        try:
                            async with get_write_session() as timeout_session:
                                from backend.domain.samba.job.repository import (
                                    SambaJobRepository,
                                )

                                timeout_repo = SambaJobRepository(timeout_session)
                                await timeout_repo.fail_job(
                                    _job_id, "수집 타임아웃 (10분)"
                                )
                                await timeout_session.commit()
                        except Exception as te:
                            logger.error(f"[잡워커] 타임아웃 잡 상태 갱신 실패: {te}")
                return

            # 전송 + 기타: 직접 실행 (인메모리 로그 공유)
            _job_id = job.id
            _job_type = job.job_type
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
            self._active_job_ids.discard(_job_id)
            self._active_tasks.pop(_job_id, None)
            if _job_type == "collect":
                _collect_site = (_job_payload or {}).get("source_site") or ""
                if _collect_site:
                    self._active_collect_sources.discard(_collect_site)
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
        from backend.domain.samba.emergency import clear_collect_cancel

        # 새 수집 시작 시 이전 취소 플래그 초기화 (이전 수집의 잔여 플래그 방지)
        clear_collect_cancel()

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
                        # 세션이 InFailedSQLTransactionError 로 aborted 상태일 수 있으므로
                        # fail_job 호출 전 반드시 rollback 하여 트랜잭션 초기화
                        try:
                            await session.rollback()
                        except Exception as rb_exc:
                            logger.warning(
                                f"[잡워커] 세션 rollback 실패(무시): {job_id} — {rb_exc}"
                            )
                        await repo.fail_job(job_id, str(e))
                        await session.commit()
                    except Exception as fail_exc:
                        logger.error(
                            f"[잡워커] 잡 상태 갱신 실패 (running 고착 가능): {job_id} — {fail_exc}"
                        )
        except Exception as e:
            logger.error(f"[잡워커] 수집 세션 에러: {job_id} — {e}")
        finally:
            await _flush_job_logs(job_id, list(_collect_log_buffer), "수집")

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
                        # 세션이 InFailedSQLTransactionError 로 aborted 상태일 수 있으므로
                        # fail_job 호출 전 반드시 rollback 하여 트랜잭션 초기화
                        try:
                            await session.rollback()
                        except Exception as rb_exc:
                            logger.warning(
                                f"[잡워커] 세션 rollback 실패(무시): {job_id} — {rb_exc}"
                            )
                        await repo.fail_job(job_id, str(e))
                        await session.commit()
                    except Exception as fail_exc:
                        logger.error(
                            f"[잡워커] 잡 상태 갱신 실패 (running 고착 가능): {job_id} — {fail_exc}"
                        )
        except Exception as e:
            logger.error(f"[잡워커] 전송 세션 에러: {job_id} — {e}")
        finally:
            await _flush_job_logs(job_id, list(_shipment_log_buffer), "전송")

    async def _run_transmit(self, job, repo, session):
        """전송 잡 실행 — 기존 shipment_service 호출."""
        from backend.domain.samba.shipment.service import (
            SambaShipmentService,
            is_cancel_requested,
            clear_cancel_transmit,
        )
        from backend.domain.samba.shipment.repository import SambaShipmentRepository
        from backend.domain.samba.emergency import clear_emergency_stop

        # 새 잡 시작 — 이전 취소의 잔존 플래그 전부 해제
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
        # 이어하기 방어: start_from이 total 이상이면 이미 완료된 잡 → complete 처리
        if start_from >= total:
            logger.warning(
                f"[잡워커] start_from({start_from}) >= total({total}) — 이미 완료된 잡"
            )
            await repo.complete_job(
                job.id,
                job.result or {"success": 0, "skipped": 0, "failed": 0},
            )
            await session.commit()
            return
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
            except Exception as exc:
                logger.warning(f"[잡워커] 취소 체크 중 DB 에러: {job.id} — {exc}")
                _is_cancelled = False

            # 배포 종료 감지 — progress 저장 + 즉시 pending 전환 후 탈출
            if self._shutting_down:
                remaining = len(product_ids) - i
                _add_job_log(
                    job.id,
                    f"배포 종료 — {i}건 완료, {remaining}건 남음 (다음 인스턴스에서 재개)",
                )
                logger.info(
                    f"[잡워커] 배포 종료 감지: {job.id} — {i}/{total}건, pending 전환"
                )
                try:
                    from sqlalchemy import text

                    await repo.update_progress(job.id, i, total)
                    # 정상 배포 중단 → 즉시 pending + attempt 리셋 (OOM 아님)
                    # graceful_stop()의 DB 쿼리와 이중 보호
                    await session.execute(
                        text(
                            "UPDATE samba_jobs SET status = 'pending', "
                            "started_at = NULL, attempt = 0 "
                            "WHERE id = :jid AND status = 'running'"
                        ),
                        {"jid": job.id},
                    )
                    await session.commit()
                except Exception as exc:
                    logger.warning(
                        f"[잡워커] 배포 종료 진행 저장 실패: {job.id} — {exc}"
                    )
                return  # fail 아닌 정상 리턴

            if is_emergency_stopped() or is_cancel_requested(job.id) or _is_cancelled:
                cancelled = len(product_ids) - i
                reason = "비상정지" if is_emergency_stopped() else "취소"
                _add_job_log(job.id, f"{reason} — {i}건 완료, {cancelled}건 중단")
                logger.info(
                    f"[잡워커] 전송 {reason}: {job.id} — {i}건 완료, {cancelled}건 중단"
                )
                await repo.fail_job(job.id, f"{reason}: {i}건 완료, {cancelled}건 중단")
                # 감지 완료 — 모든 플래그 정리
                clear_cancel_transmit()
                clear_emergency_stop()
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
                    _source = (prod.source_site or "").upper() if prod else ""
                    prod_name = f"{_brand} {_raw_name}".strip()[:35]
                    if _style:
                        prod_name = f"{prod_name} {_style}"
                    if site_pid:
                        prod_name = f"{prod_name} ({site_pid})"
                    if _source:
                        prod_name = f"[{_source}] {prod_name}"

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
                            err = str(tx_error.get(acc_id, "실패"))[:500]
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
                                f"[{i + 1}/{total}] {prod_name}: {str(err_msg)[:500]}",
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
                    except Exception as exc:
                        logger.warning(f"[잡워커] 세션 롤백 실패: {job.id} — {exc}")

        # 2차 재시도 — 실패 상품만 (건별 독립 세션)
        retry_success = 0
        if failed_pids:
            _add_job_log(job.id, f"재시도 시작 — 실패 {len(failed_pids)}건")
            await asyncio.sleep(3)  # 세마포어 해제 대기
            for ri, pid in enumerate(failed_pids):
                from backend.domain.samba.emergency import is_emergency_stopped

                if (
                    is_emergency_stopped()
                    or is_cancel_requested(job.id)
                    or await repo.is_cancelled(job.id)
                ):
                    clear_cancel_transmit()
                    clear_emergency_stop()
                    break
                try:
                    async with get_write_session() as retry_session:
                        retry_cp = SambaCollectedProductRepository(retry_session)
                        prod = await retry_cp.get_async(pid)
                        site_pid = prod.site_product_id if prod else ""
                        _source = (prod.source_site or "").upper() if prod else ""
                        prod_name = prod.name[:30] if prod and prod.name else pid[-8:]
                        if site_pid:
                            prod_name = f"{prod_name} ({site_pid})"
                        if _source:
                            prod_name = f"[{_source}] {prod_name}"
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
        _gi = payload.get("group_index")
        _gt = payload.get("group_total")
        _prefix = f"({_gi}/{_gt})" if _gi and _gt else f"[{site}]"
        _add_job_log(job.id, f"{_prefix} [{sf.name}] 수집 시작", job_type="collect")

        # 직접 API 소싱처 (서버 HTTP)
        DIRECT_API_SITES = {"FashionPlus", "Nike", "Adidas", "LOTTEON", "SSG"}
        # 확장앱 기반 소싱처 (소싱큐)
        EXTENSION_SITES = {
            "ABCmart",
            "GrandStage",
            "REXMONDE",
            "GSShop",
            "ElandMall",
            "SSF",
        }

        # 잡 전체 10분 타임아웃 가드 — 무한 hang으로 running 고착되는 현상 방지
        _JOB_TIMEOUT_SEC = 600

        if site in DIRECT_API_SITES:
            try:
                await asyncio.wait_for(
                    self._collect_direct_api(job, sf, session, repo),
                    timeout=_JOB_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"[잡워커] {site} 수집 {_JOB_TIMEOUT_SEC}초 타임아웃: {job.id}"
                )
                await repo.fail_job(
                    job.id,
                    f"{site} 수집 {_JOB_TIMEOUT_SEC // 60}분 타임아웃 — 응답 지연으로 자동 종료",
                )
            return

        if site in EXTENSION_SITES:
            try:
                await asyncio.wait_for(
                    self._collect_direct_api(job, sf, session, repo),
                    timeout=_JOB_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"[잡워커] {site} 수집 {_JOB_TIMEOUT_SEC}초 타임아웃: {job.id}"
                )
                await repo.fail_job(
                    job.id,
                    f"{site} 수집 {_JOB_TIMEOUT_SEC // 60}분 타임아웃 — 응답 지연으로 자동 종료",
                )
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
        _include_sold_out = False

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
                _include_sold_out = qs.get("includeSoldOut", [""])[0] == "1"
                _brand_filter = qs.get("brand", [""])[0]
                _min_price_raw = qs.get("minPrice", [""])[0]
                _max_price_raw = qs.get("maxPrice", [""])[0]
                _gf_filter = qs.get("gf", ["A"])[0]
                _category_filter = qs.get("category", [""])[0]
                _min_price = int(_min_price_raw) if _min_price_raw.isdigit() else None
                _max_price = int(_max_price_raw) if _max_price_raw.isdigit() else None
        except Exception as exc:
            logger.warning(f"[잡워커] 검색 URL 파싱 실패: {exc}")

        # 기존 수집 수 확인
        requested_count = sf.requested_count or 100
        count_stmt = select(_func.count()).where(CPModel.search_filter_id == filter_id)
        existing_count = (await session.execute(count_stmt)).scalar() or 0
        remaining = max(0, requested_count - existing_count)

        if remaining <= 0:
            _add_job_log(
                job.id,
                f"{_prefix} 이미 {existing_count}개 수집됨 (요청: {requested_count}개)",
                job_type="collect",
            )
            await repo.complete_job(
                job.id,
                {
                    "saved": 0,
                    "message": f"이미 {existing_count}개 수집됨 (요청: {requested_count}개)",
                },
            )
            return

        _add_job_log(
            job.id,
            f"{_prefix} [{sf.name}] 잔여 {remaining}건 수집 시작 (기존 {existing_count}건)",
            job_type="collect",
        )
        await repo.update_progress(job.id, existing_count, requested_count)

        # 수집 루프
        total_saved = 0
        total_skipped = 0
        search_page = 1
        empty_pages = 0  # 연속 신규 0건 페이지 카운터 (잡 간 오염 방지용 로컬 변수)
        max_pages = 100  # API totalPages 기반으로 동적 조정 (초기값)
        _collected_sold_out = 0

        while total_saved < remaining and search_page <= max_pages:
            # 취소 확인 — 인메모리 플래그 우선(빠름), DB 조회는 최후(멀티인스턴스 대비)
            from backend.domain.samba.emergency import (
                clear_collect_cancel,
                is_collect_cancel_requested,
                is_emergency_stopped,
            )

            if (
                is_collect_cancel_requested()
                or is_emergency_stopped()
                or await repo.is_cancelled(job.id)
            ):
                logger.info(f"[잡워커] 수집 취소됨: {job.id}")
                # DB 상태 확실히 CANCELLED — stuck recovery 재시작 방지
                try:
                    await repo.cancel_job(job.id)
                    await session.commit()
                except Exception as _e:
                    logger.warning(f"[잡워커] 취소 상태 저장 실패: {job.id} — {_e}")
                _add_job_log(job.id, "수집 취소됨", job_type="collect")
                clear_collect_cancel()  # 다음 수집을 위해 해제
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

            # 중복 필터링 (전역 기준 — unique constraint와 동일한 범위)
            candidate_ids = [
                str(item.get("siteProductId", item.get("goodsNo", "")))
                for item in search_items
            ]
            existing_result = await session.execute(
                select(CPModel.site_product_id).where(
                    CPModel.source_site == site,
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
                nonlocal total_skipped, _rate_limited, _collected_sold_out
                if _rate_limited:
                    return None
                async with _collect_sem:
                    try:
                        detail = await client.get_goods_detail(
                            goods_no, _shared_client=_shared_http
                        )
                        if not detail or not detail.get("name"):
                            return None
                        _is_sold = detail.get("saleStatus") == "sold_out" or detail.get(
                            "isOutOfStock"
                        )
                        if _is_sold:
                            if not _include_sold_out:
                                total_skipped += 1
                                return None
                            _collected_sold_out += 1
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
                        logger.warning(
                            f"[잡워커] 수집 실패 {goods_no}: {type(e).__name__}: {e}"
                        )
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
                # 10건 단위 진행 로그
                if total_saved % 10 == 0 or total_saved >= remaining:
                    _add_job_log(
                        job.id,
                        f"{_prefix} [{sf.name}] [{existing_count + total_saved}/{requested_count}] 수집 중...",
                        job_type="collect",
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
                        "source_site_margins": pr.get("sourceSiteMargins", {}),
                    }
                count = await svc.apply_policy_to_filter_products(
                    filter_id, sf.applied_policy_id, policy_data
                )
                policy_msg = f"정책 적용: {count}개"
            except Exception as e:
                logger.error(f"[잡워커] 정책 전파 실패: {e}")

        _in_stock = total_saved - _collected_sold_out
        _parts = [f"신규 {total_saved}건"]
        if _in_stock > 0 or _collected_sold_out > 0:
            _parts.append(f"재고 {_in_stock}건 | 품절 {_collected_sold_out}건")
        if total_skipped > 0:
            _parts.append(f"중복/스킵 {total_skipped}건")
        if policy_msg:
            _parts.append(policy_msg)
        _add_job_log(
            job.id,
            f"{_prefix} [{sf.name}] 수집 완료: {' | '.join(_parts)}",
            job_type="collect",
        )

        await repo.complete_job(
            job.id,
            {
                "saved": total_saved,
                "skipped": total_skipped,
                "policy": policy_msg,
                "in_stock_count": _in_stock,
                "sold_out_count": _collected_sold_out,
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
        _original_url = keyword  # URL 원본 보존 (카테고리 필터 포함)
        requested_count = max(sf.requested_count or 100, 10)
        _payload = job.payload or {}
        _dgi = _payload.get("group_index")
        _dgt = _payload.get("group_total")
        _dprefix = f"({_dgi}/{_dgt})" if _dgi and _dgt else f"[{site}]"

        # URL에서 키워드/필터 추출
        _search_kwargs: dict = {}
        _use_max_discount = False
        _include_sold_out = False
        try:
            from urllib.parse import urlparse, parse_qs

            parsed = urlparse(keyword)
            if parsed.scheme:
                qs = parse_qs(parsed.query)
                _use_max_discount = qs.get("maxDiscount", [""])[0] == "1"
                _include_sold_out = qs.get("includeSoldOut", [""])[0] == "1"
                # 소싱처별 키워드 파라미터: LOTTEON=q, GSShop=tq, SSG=query, FashionPlus=searchWord
                keyword = qs.get(
                    "q",
                    qs.get(
                        "tq",
                        qs.get(
                            "query",
                            qs.get("keyword", qs.get("searchWord", [keyword])),
                        ),
                    ),
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
                # SSG repBrandId 파라미터 → brand_ids 리스트로 전달
                _rep_brand_id = qs.get("repBrandId", [""])[0]
                if _rep_brand_id:
                    _search_kwargs["brand_ids"] = _rep_brand_id.split("|")
                # SSG ctgId 파라미터 → 검색 URL에 카테고리 필터 전달
                # 하위호환: 기존 dispCtgId 그룹도 지원
                _ctg_id = qs.get("ctgId", [""])[0] or qs.get("dispCtgId", [""])[0]
                if _ctg_id:
                    _search_kwargs["ctg_id"] = _ctg_id
                _ctg_lv = qs.get("ctgLv", [""])[0]
                if _ctg_lv:
                    _search_kwargs["ctg_lv"] = _ctg_lv
                # SSG ctgPath 파라미터 → 전시카테고리 전체 경로 (그룹 생성 시 저장)
                _ctg_path = qs.get("ctgPath", [""])[0]
                if _ctg_path:
                    _search_kwargs["ctgPath"] = _ctg_path
                # skipDetail 옵션
                if qs.get("skipDetail", [""])[0] == "1":
                    _search_kwargs["_skip_detail"] = True
        except Exception as exc:
            logger.warning(f"[잡워커] 검색 URL 파싱 실패: {exc}")

        # 기존 수집 수 확인
        count_stmt = select(_func.count()).where(CPModel.search_filter_id == filter_id)
        existing_count = (await session.execute(count_stmt)).scalar() or 0
        remaining = max(0, requested_count - existing_count)
        if remaining <= 0:
            _add_job_log(
                job.id,
                f"{_dprefix} [{sf.name}] 이미 {existing_count}개 수집됨",
                job_type="collect",
            )
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
        elif site == "ABCmart":
            from backend.core.config import settings as _abc_cfg
            from backend.domain.samba.proxy.abcmart import ARTSourcingClient

            # Cloud Run IP가 a-rt.com에 차단되는 현상 우회 — 무신사/GSShop과 동일 프록시 풀 공유
            _abc_proxies: list[str] = []
            if _abc_cfg.collect_proxy_url:
                _abc_proxies.append(_abc_cfg.collect_proxy_url.strip())
            if _abc_cfg.proxy_urls:
                _abc_proxies.extend(
                    [p.strip() for p in _abc_cfg.proxy_urls.split(",") if p.strip()]
                )
            client = ARTSourcingClient(proxy_pool=_abc_proxies or None)
        elif site == "GSShop":
            from backend.core.config import settings as _gs_cfg
            from backend.domain.samba.proxy.gsshop_sourcing import (
                GsShopSourcingClient,
            )

            _gs_proxies: list[str] = []
            if _gs_cfg.collect_proxy_url:
                _gs_proxies.append(_gs_cfg.collect_proxy_url.strip())
            if _gs_cfg.proxy_urls:
                _gs_proxies.extend(
                    [p.strip() for p in _gs_cfg.proxy_urls.split(",") if p.strip()]
                )
            client = GsShopSourcingClient(proxy_pool=_gs_proxies or None)
        elif site == "SSG":
            from backend.domain.samba.proxy.ssg_sourcing import (
                RateLimitError as SSGRateLimitError,
            )
            from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

            client = SSGSourcingClient()

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
                # sf.keyword가 이미 URL이면 SourcingQueue에 직접 전달 (템플릿 이중 치환 방지)
                # 상대 URL(/shop/...)도 절대 URL로 변환하여 전달
                _kw_raw = sf.keyword or ""
                if _kw_raw.startswith("http"):
                    _sq_url = _kw_raw
                elif _kw_raw.startswith("/"):
                    # 상대 URL → 소싱처 도메인 붙여서 절대 URL 변환
                    _site_domains = {
                        "GSShop": "https://www.gsshop.com",
                        "ABCmart": "https://www.a-rt.com",
                        "GrandStage": "https://www.a-rt.com",
                        "REXMONDE": "https://www.okmall.com",
                        "ElandMall": "https://www.elandmall.com",
                        "SSF": "https://www.ssfshop.com",
                        "SSG": "https://www.ssg.com",
                    }
                    _domain = _site_domains.get(site, "")
                    _sq_url = f"{_domain}{_kw_raw}" if _domain else ""
                else:
                    _sq_url = ""
                _req_id, _future = SourcingQueue.add_search_job(
                    site, keyword, url=_sq_url
                )
                ext_result = await asyncio.wait_for(_future, timeout=180)
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
                except Exception as exc:
                    logger.warning(f"[잡워커] LOTTEON 브랜드 파라미터 파싱 실패: {exc}")

            try:
                if _per_brand_keywords:
                    items_list = []
                    seen_pids: set[str] = set()
                    # LOTTEON 전수 페이징: 브랜드당 qapi 상한 2,100건 전체 수집
                    # BC코드 사후 필터링 특성상 수집 모수가 많아야 실제 카테고리 상품 확보 가능
                    # (search() 내부에서 _MAX_QAPI_OFFSET=2100 하드캡 처리 중)
                    per_max = (
                        2100
                        if (site == "LOTTEON" and sf.category_filter)
                        else max(remaining * 2, 100)
                    )
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
                    # 카테고리필터가 있는 소싱처: 전체 검색 후 사후 필터링
                    # SSG: 검색 URL에 dispCtgId가 이미 포함되므로 상세 재검증 불필요
                    # 중복 제거 여유분 5건만 추가해서 검색
                    if site == "SSG" and sf.category_filter:
                        _max = remaining + 5
                    else:
                        _max = (
                            9999
                            if (
                                site in ("Nike", "ABCmart", "GSShop", "SSG", "LOTTEON")
                                and sf.category_filter
                            )
                            else max(remaining * 2, 100)
                        )
                    # 검색 캐시: 동일 브랜드 그룹 수집 시 전수 검색 1회만 실행
                    # ABCmart: DB 캐시 (다중 Cloud Run 인스턴스 공유), 나머지: 인메모리 캐시
                    import time as _time

                    _cache_key = (site, keyword)
                    _cached = self._search_cache.get(_cache_key)
                    _cache_ttl = 300  # 5분 (인메모리)
                    _abc_db_cache_hit = False

                    # ABCmart: DB 캐시 우선 조회 (인스턴스 간 공유)
                    if (
                        site == "ABCmart"
                        and sf.category_filter
                        and not (_cached and _time.time() - _cached[1] < _cache_ttl)
                    ):
                        from backend.domain.samba.collector.model import (
                            SambaSearchCache as _SCache,
                        )
                        from datetime import timedelta as _td

                        _db_cache = await session.execute(
                            select(_SCache)
                            .where(
                                _SCache.source_site == site,
                                _SCache.keyword == keyword,
                                _SCache.created_at
                                > datetime.now(tz=timezone.utc) - _td(minutes=60),
                            )
                            .order_by(_SCache.created_at.desc())
                            .limit(1)
                        )
                        _db_cache_row = _db_cache.scalars().first()
                        if _db_cache_row and _db_cache_row.products:
                            items_list = list(_db_cache_row.products)
                            _abc_db_cache_hit = True
                            logger.info(
                                f"[잡워커] ABCmart DB 캐시 히트 '{keyword}' → {len(items_list)}건"
                            )
                            _add_job_log(
                                job.id,
                                f"{_dprefix} [{sf.name}] 검색 완료: {len(items_list):,}건 (캐시)",
                                job_type="collect",
                            )
                            # 인메모리 캐시에도 복사 (같은 인스턴스 내 후속 잡 최적화)
                            self._search_cache[_cache_key] = (
                                items_list,
                                _time.time(),
                            )

                    if not _abc_db_cache_hit and (
                        _cached
                        and _time.time() - _cached[1] < _cache_ttl
                        and (
                            site in ("Nike", "ABCmart", "GSShop", "LOTTEON")
                            and sf.category_filter
                        )
                    ):
                        items_list = list(_cached[0])
                        logger.info(
                            f"[잡워커] {site} 검색 캐시 히트 '{keyword}' → {len(items_list)}건"
                        )
                        _add_job_log(
                            job.id,
                            f"{_dprefix} [{sf.name}] 검색 완료: {len(items_list):,}건 (캐시)",
                            job_type="collect",
                        )
                    elif not _abc_db_cache_hit:
                        # GSShop: 원본 URL(카테고리 필터 포함) 전달
                        if site == "GSShop" and _original_url.startswith("http"):
                            _search_kwargs["url"] = _original_url
                        # ABCmart: ABC + GS 동시 검색 (로컬 테스트: 순차 8.4s → 병렬 6.0s)
                        if site == "ABCmart" and sf.category_filter:
                            # 검색 직전 취소 체크 (병렬 검색 6초 걸림)
                            from backend.domain.samba.emergency import (
                                clear_collect_cancel as _clear_cc2,
                                is_collect_cancel_requested as _is_cc2,
                                is_emergency_stopped as _is_es2,
                            )

                            if _is_cc2() or _is_es2():
                                logger.info(f"[잡워커] {site} 검색 취소: {job.id}")
                                _clear_cc2()
                                return
                            from backend.core.config import settings as _gs_cfg2
                            from backend.domain.samba.proxy.abcmart import (
                                ARTSourcingClient as _ART,
                            )

                            # GrandStage도 동일 프록시 풀 사용 (a-rt.com 차단 우회)
                            _gs_proxies2: list[str] = []
                            if _gs_cfg2.collect_proxy_url:
                                _gs_proxies2.append(_gs_cfg2.collect_proxy_url.strip())
                            if _gs_cfg2.proxy_urls:
                                _gs_proxies2.extend(
                                    [
                                        p.strip()
                                        for p in _gs_cfg2.proxy_urls.split(",")
                                        if p.strip()
                                    ]
                                )
                            _gs = _ART("10002", proxy_pool=_gs_proxies2 or None)
                            # 프로덕션(Cloud Run IP)에서 a-rt.com이 응답을 씹는 경우 대비 120초 가드
                            try:
                                _abc_res, _gs_res = await asyncio.wait_for(
                                    asyncio.gather(
                                        client.search(
                                            keyword,
                                            max_count=_max,
                                            **_search_kwargs,
                                        ),
                                        _gs.search(
                                            keyword,
                                            max_count=_max,
                                            **_search_kwargs,
                                        ),
                                        return_exceptions=True,
                                    ),
                                    timeout=120,
                                )
                            except asyncio.TimeoutError:
                                logger.warning(
                                    f"[잡워커] ABCmart+GS 검색 120초 타임아웃: {keyword}"
                                )
                                await repo.fail_job(
                                    job.id,
                                    "ABCmart 응답 지연 (120초 타임아웃) — a-rt.com 응답 없음",
                                )
                                return
                            # gather 내부 예외는 개별적으로 처리
                            if isinstance(_abc_res, Exception):
                                logger.warning(
                                    f"[잡워커] ABCmart 검색 예외: {_abc_res}"
                                )
                                _abc_res = {"products": [], "total": 0}
                            if isinstance(_gs_res, Exception):
                                logger.warning(
                                    f"[잡워커] GrandStage 검색 예외: {_gs_res}"
                                )
                                _gs_res = {"products": [], "total": 0}
                            result = _abc_res
                            items_list = result.get("products", [])
                            _gs_products = _gs_res.get("products", [])
                            if _gs_products:
                                _seen = {
                                    p.get("site_product_id", "")
                                    for p in items_list
                                    if p.get("site_product_id")
                                }
                                for p in _gs_products:
                                    pid = p.get("site_product_id", "")
                                    if pid and pid not in _seen:
                                        _seen.add(pid)
                                        items_list.append(p)
                                logger.info(
                                    f"[잡워커] ABCmart+GS 병렬 병합: ABC {len(result.get('products', []))}건 "
                                    f"+ GS {len(_gs_products)}건 → 총 {len(items_list)}건"
                                )
                        else:
                            # 단일 검색에도 120초 가드 — 카테고리필터 없는 경로 hang 방지
                            try:
                                result = await asyncio.wait_for(
                                    client.search(
                                        keyword, max_count=_max, **_search_kwargs
                                    ),
                                    timeout=120,
                                )
                            except asyncio.TimeoutError:
                                logger.warning(
                                    f"[잡워커] {site} 검색 120초 타임아웃: {keyword}"
                                )
                                await repo.fail_job(
                                    job.id,
                                    f"{site} 검색 응답 지연 (120초 타임아웃)",
                                )
                                return
                            items_list = result.get("products", [])
                        logger.info(
                            f"[잡워커] {site} 검색 '{keyword}' → {len(items_list)}건"
                        )
                        _add_job_log(
                            job.id,
                            f"{_dprefix} [{sf.name}] 검색 완료: {len(items_list):,}건",
                            job_type="collect",
                        )
                        # 전수 검색 결과 캐시 저장
                        # ABCmart: GS 병합이 실패(0개)한 경우 캐시 저장 금지
                        # → GS 실패 캐시가 전파되어 이후 모든 SF 잡이 GS 아이템 누락하는 현상 방지
                        _abc_only_count = len(result.get("products", []))
                        _gs_merged_count = len(items_list) - _abc_only_count
                        _gs_was_attempted = site == "ABCmart" and sf.category_filter
                        _cache_ok = not _gs_was_attempted or _gs_merged_count > 0
                        if not _cache_ok:
                            logger.warning(
                                f"[잡워커] ABCmart GS 검색 실패로 캐시 저장 스킵 "
                                f"(ABC {_abc_only_count}건, GS 0건) — 다음 잡에서 재시도"
                            )
                        if (
                            (
                                site in ("Nike", "ABCmart", "GSShop", "LOTTEON")
                                and sf.category_filter
                            )
                            and items_list
                            and _cache_ok
                        ):
                            self._search_cache[_cache_key] = (
                                items_list,
                                _time.time(),
                            )
                            # ABCmart: DB 캐시에도 저장 (다중 인스턴스 공유)
                            # 기존 항목을 먼저 삭제하고 새로 저장 (stale 데이터 방지)
                            if site == "ABCmart":
                                from backend.domain.samba.collector.model import (
                                    SambaSearchCache as _SCache,
                                )
                                from sqlalchemy import delete as _sa_delete

                                _cache_data = {
                                    "id": generate_search_cache_id(),
                                    "tenant_id": getattr(sf, "tenant_id", None),
                                    "source_site": site,
                                    "keyword": keyword,
                                    "products": items_list,
                                    "ttl_minutes": 60,
                                    "created_at": datetime.now(tz=timezone.utc),
                                }
                                try:
                                    # 동일 (source_site, keyword) 기존 캐시 전부 삭제
                                    await session.execute(
                                        _sa_delete(_SCache).where(
                                            _SCache.source_site == site,
                                            _SCache.keyword == keyword,
                                        )
                                    )
                                    session.add(_SCache(**_cache_data))
                                    await session.flush()
                                    logger.info(
                                        f"[잡워커] ABCmart DB 캐시 갱신: '{keyword}' {len(items_list)}건"
                                    )
                                except Exception as _ce:
                                    await session.rollback()
                                    logger.warning(
                                        f"[잡워커] ABCmart DB 캐시 저장 실패 (무시): {_ce}"
                                    )
            except Exception as e:
                await repo.fail_job(job.id, f"검색 실패: {e}")
                return

        # Nike: category_filter("성별_세분류")로 검색 결과 사후 필터링
        if site == "Nike" and sf.category_filter:
            # "남성_러닝화" → c2="남성", c3="러닝화"
            # "가방" (언더스코어 없음) → c2="", c3="가방" (성별 없는 카테고리)
            _parts = sf.category_filter.split("_", 1)
            if len(_parts) == 2:
                _filter_c2, _filter_c3 = _parts[0], _parts[1]
            else:
                # 언더스코어 없으면 세분류만 (성별 없는 카테고리: 가방, 모자, 양말 등)
                _filter_c2, _filter_c3 = "", _parts[0]
            before = len(items_list)
            filtered = []
            for item in items_list:
                ic2 = item.get("category2", "")
                ic3 = item.get("category3", "")
                # 성별+세분류 모두 일치해야 통과
                if _filter_c2 and ic2 != _filter_c2:
                    continue
                if _filter_c3 and ic3 != _filter_c3:
                    continue
                filtered.append(item)
            items_list = filtered
            logger.info(
                f"[잡워커] Nike 카테고리 필터 {sf.category_filter}: {before}→{len(items_list)}건"
            )

        # ABCmart: category_filter(카테고리 코드+이름) 로 검색 결과 사후 필터링
        # ABC-MART/GrandStage 카테고리 코드가 채널별로 다르므로
        # 코드 매칭 + 카테고리명(path) 매칭 병행
        if site == "ABCmart" and sf.category_filter:
            # [DIAG] 필터 진입 전 source_site × category_code 분포 확인
            from collections import Counter as _Ctr  # noqa: PLC0415

            _diag = _Ctr(
                (
                    item.get("source_site", ""),
                    item.get("category_code", "") or "(empty)",
                )
                for item in items_list
            )
            logger.info(
                f"[잡워커][DIAG] ABCmart filter 진입 sf.category_filter={sf.category_filter!r} "
                f"items={len(items_list)} 분포 TOP10={_diag.most_common(10)}"
            )
            _gs_samples = [
                (item.get("category_code", ""), item.get("category", ""))
                for item in items_list
                if item.get("source_site") == "GrandStage"
            ][:3]
            logger.info(f"[잡워커][DIAG] GS 샘플: {_gs_samples}")
        if site == "ABCmart" and sf.category_filter:
            before = len(items_list)
            # ABC-MART 코드에 대응하는 카테고리 이름(path) 수집
            _target_cat_names: set[str] = set()
            for item in items_list:
                if (item.get("category_code") or "") == sf.category_filter:
                    _cn = item.get("category") or ""
                    if _cn:
                        _target_cat_names.add(_cn)
            # 코드 일치 OR 같은 카테고리명의 GS 상품 포함
            items_list = [
                item
                for item in items_list
                if (item.get("category_code") or "") == sf.category_filter
                or (item.get("category") or "") in _target_cat_names
            ]
            logger.info(
                f"[잡워커] ABCmart 카테고리 필터 {sf.category_filter}: {before}→{len(items_list)}건"
                f" (카테고리명 매칭: {_target_cat_names})"
            )

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
            except Exception as exc:
                logger.warning(f"[잡워커] LOTTEON 브랜드 필터 파싱 실패: {exc}")

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
        # URL의 categoryName 파라미터 우선 사용 — _CATEGORY_MAP은 ID와 이름이 불일치할 수 있음
        _category1_name = ""
        _fp_cat1 = ""
        _fp_cat2 = ""
        _fp_cat3 = ""
        # SSG: ctgPath URL 파라미터에서 전시카테고리 전체 경로 복원
        _ssg_cat = ""
        _ssg_cat1 = ""
        _ssg_cat2 = ""
        _ssg_cat3 = ""
        _ssg_cat4 = ""
        if site == "SSG":
            _ctg_path_ssg = _search_kwargs.get("ctgPath", "")
            if _ctg_path_ssg:
                _ssg_parts = _ctg_path_ssg.split(" > ")
                _ssg_cat = _ctg_path_ssg
                _ssg_cat1 = _ssg_parts[0] if _ssg_parts else ""
                _ssg_cat2 = _ssg_parts[1] if len(_ssg_parts) > 1 else ""
                _ssg_cat3 = _ssg_parts[2] if len(_ssg_parts) > 2 else ""
                _ssg_cat4 = _ssg_parts[3] if len(_ssg_parts) > 3 else ""
                logger.debug(f"[잡워커] SSG ctgPath 카테고리: {_ssg_cat}")
        if site == "FashionPlus":
            _fp_cat1 = qs.get("category1Name", [""])[0]
            _fp_cat2 = qs.get("category2Name", [""])[0]
            _fp_cat3 = qs.get("category3Name", [""])[0]
            _fp_path_parts = [n for n in [_fp_cat1, _fp_cat2, _fp_cat3] if n]
            if _fp_path_parts:
                # URL에 이름 파라미터가 있으면 경로 재구성 (예: "잡화 > 가방 > 백팩")
                _category1_name = " > ".join(_fp_path_parts)
            elif _search_kwargs.get("category1Id"):
                # 구 URL(이름 파라미터 없음) 폴백 — _CATEGORY_MAP 사용
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
                    await repo.update_progress(job.id, done, len(new_items))
                    logger.info(
                        f"[잡워커] LOTTEON 상세 선취합 [{done}/{len(new_items)}]"
                    )
                    _add_job_log(
                        job.id,
                        f"[{site}] [{sf.name}] 상세 조회 [{done:,}/{len(new_items):,}]",
                        job_type="collect",
                    )
                    await asyncio.sleep(0.3)
                logger.info(
                    f"[잡워커] LOTTEON 상세 선취합 완료: {len(_lotteon_details)}/{len(new_items)}건 성공"
                )

        # Nike: 저장 전 10건 병렬로 상세 정보 선취합
        _nike_details: dict[str, dict[str, Any]] = {}
        if site == "Nike" and client:
            new_items = [
                it
                for it in items_list
                if str(it.get("site_product_id", "")) not in existing_ids
            ][:remaining]
            if new_items:
                logger.info(
                    f"[잡워커] Nike 상세 선취합 시작: {len(new_items)}건 (10건 병렬)"
                )
                _NK_BATCH = 10
                for batch_start in range(0, len(new_items), _NK_BATCH):
                    batch = new_items[batch_start : batch_start + _NK_BATCH]
                    details = await asyncio.gather(
                        *(
                            client.get_detail(
                                str(it.get("site_product_id", "")),
                                pdp_url=it.get("url") or it.get("source_url"),
                                base_info=it,
                            )
                            for it in batch
                        ),
                        return_exceptions=True,
                    )
                    for it, det in zip(batch, details):
                        pid = str(it.get("site_product_id", ""))
                        if isinstance(det, Exception):
                            logger.warning(
                                f"[잡워커] Nike 상세 선취합 실패 {pid}: {det}"
                            )
                            continue
                        if det:
                            _nike_details[pid] = det
                    done = min(batch_start + _NK_BATCH, len(new_items))
                    await repo.update_progress(job.id, done, len(new_items))
                    logger.info(f"[잡워커] Nike 상세 선취합 [{done}/{len(new_items)}]")
                    _add_job_log(
                        job.id,
                        f"[{site}] [{sf.name}] 상세 조회 [{done:,}/{len(new_items):,}]",
                        job_type="collect",
                    )
                    await asyncio.sleep(0.15)
                logger.info(
                    f"[잡워커] Nike 상세 선취합 완료: {len(_nike_details)}/{len(new_items)}건 성공"
                )

        # GSShop: 선취합 + 카테고리 필터 (검색 결과에 이름/카테고리 없으므로 상세 조회 필수)
        _gsshop_details: dict[str, dict[str, Any]] = {}
        if site == "GSShop" and client:
            new_items = [
                it
                for it in items_list
                if str(it.get("site_product_id", "")) not in existing_ids
            ][:remaining]
            if new_items:
                logger.info(
                    f"[잡워커] GSShop 상세 선취합 시작: {len(new_items)}건 (20건 병렬)"
                )
                _GS_BATCH = 20
                _gs_cat_filter = sf.category_filter or ""
                # 카테고리 필터: "카테고리명" 또는 "대>중>소" 형태
                _gs_filter_parts = [
                    p.strip()
                    for p in _gs_cat_filter.replace(" > ", "_").split("_")
                    if p.strip()
                ]
                for batch_start in range(0, len(new_items), _GS_BATCH):
                    batch = new_items[batch_start : batch_start + _GS_BATCH]
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
                            logger.debug(
                                f"[잡워커] GSShop 상세 선취합 실패 {pid}: {det}"
                            )
                            continue
                        if not det or not det.get("name"):
                            continue
                        # 카테고리 필터 적용
                        if _gs_filter_parts:
                            _det_cats = [
                                det.get("category1", ""),
                                det.get("category2", ""),
                                det.get("category3", ""),
                                det.get("category4", ""),
                            ]
                            _det_cat_str = " ".join(c for c in _det_cats if c).lower()
                            _matched = all(
                                fp.lower() in _det_cat_str for fp in _gs_filter_parts
                            )
                            if not _matched:
                                continue
                        _gsshop_details[pid] = det
                    done = min(batch_start + _GS_BATCH, len(new_items))
                    await repo.update_progress(job.id, done, len(new_items))
                    logger.info(
                        f"[잡워커] GSShop 상세 선취합 [{done}/{len(new_items)}]"
                        f" 카테고리 통과: {len(_gsshop_details)}건"
                    )
                    _add_job_log(
                        job.id,
                        f"[{site}] [{sf.name}] 상세 조회 [{done:,}/{len(new_items):,}]",
                        job_type="collect",
                    )
                logger.info(
                    f"[잡워커] GSShop 상세 선취합 완료:"
                    f" {len(_gsshop_details)}/{len(new_items)}건"
                    f" (카테고리 필터: {_gs_cat_filter or '없음'})"
                )
            # GSShop: 선취합 결과로 items_list 교체 (카테고리 통과 상품만)
            if _gsshop_details:
                items_list = [
                    it
                    for it in items_list
                    if str(it.get("site_product_id", "")) in _gsshop_details
                ]

        # SSG: 저장 전 상세 정보 선취합 (카테고리/원가/고시정보 보충 필수)
        _ssg_details: dict[str, dict[str, Any]] = {}
        if site == "SSG" and client:
            _ssg_cat_filter = sf.category_filter or None
            new_items = [
                it
                for it in items_list
                if str(it.get("site_product_id", "")) not in existing_ids
            ]
            # 카테고리 필터 유무 관계없이 remaining개로 제한
            # SSG 검색 URL에 dispCtgId가 이미 포함되므로 추가 재검증 불필요
            new_items = new_items[:remaining]
            if new_items:
                logger.info(
                    f"[잡워커] SSG 상세 선취합 시작: {len(new_items)}건 (페이지 순서 기준)"
                    + (
                        f" | 카테고리 필터: {_ssg_cat_filter}"
                        if _ssg_cat_filter
                        else ""
                    )
                )
                _add_job_log(
                    job.id,
                    f"[{site}] [{sf.name}] 상세 조회 시작: {len(new_items):,}건",
                    job_type="collect",
                )
                # 2건씩 병렬 배치 + TCP 연결 재사용
                # 5건 병렬은 SSG 429를 더 빨리 유발하므로 2건으로 조정
                import httpx as _httpx_ssg

                _SSG_BATCH = 2
                _ssg_matched = 0
                _shared_http = _httpx_ssg.AsyncClient(
                    timeout=_httpx_ssg.Timeout(30, connect=10.0),
                    follow_redirects=True,
                )

                async def _fetch_ssg_detail(
                    _pid: str,
                ) -> tuple[str, dict[str, Any]]:
                    """개별 SSG 상세 조회 (rate limit 재시도 포함)."""
                    for attempt in range(3):
                        try:
                            det = await client.get_detail(
                                _pid, _shared_client=_shared_http
                            )
                            return (_pid, det)
                        except SSGRateLimitError as _rl:
                            wait_seconds = max(
                                5,
                                min(int(getattr(_rl, "retry_after", 60) or 60), 60),
                            )
                            logger.warning(
                                f"[잡워커] SSG 상세 rate limit {_pid}: "
                                f"wait={wait_seconds}s retry={attempt + 1}/3"
                            )
                            _add_job_log(
                                job.id,
                                f"[{site}] 속도 제한 — {wait_seconds}초 대기 중... (재시도 {attempt + 1}/3)",
                                job_type="collect",
                            )
                            if attempt >= 2:
                                raise
                            await asyncio.sleep(wait_seconds)
                    return (_pid, {})

                try:
                    for batch_start in range(0, len(new_items), _SSG_BATCH):
                        batch = new_items[batch_start : batch_start + _SSG_BATCH]
                        batch_pids = [
                            str(it.get("site_product_id", "")) for it in batch
                        ]

                        # 배치 내 병렬 상세 조회
                        results = await asyncio.gather(
                            *(_fetch_ssg_detail(pid) for pid in batch_pids),
                            return_exceptions=True,
                        )

                        for pid, res in zip(batch_pids, results):
                            if isinstance(res, Exception):
                                logger.warning(f"[잡워커] SSG 상세 실패 {pid}: {res}")
                                continue
                            _, det = res
                            if det:
                                # 검색 URL에 dispCtgId가 이미 포함되므로 재검증 없이 저장
                                _ssg_details[pid] = det

                        done = min(batch_start + _SSG_BATCH, len(new_items))
                        await repo.update_progress(job.id, done, len(new_items))
                        _add_job_log(
                            job.id,
                            f"[{site}] [{sf.name}] 상세 조회 [{done:,}/{len(new_items):,}]",
                            job_type="collect",
                        )
                        logger.info(
                            f"[잡워커] SSG 상세 선취합 [{done}/{len(new_items)}]"
                        )
                        # 배치 간 딜레이 (마지막 배치 후 생략)
                        # 2건 병렬 + 1.5초 = 약 1.3건/초 → SSG 차단 임계값 이하 유지
                        if batch_start + _SSG_BATCH < len(new_items):
                            await asyncio.sleep(1.5)
                finally:
                    await _shared_http.aclose()

                logger.info(
                    f"[잡워커] SSG 상세 선취합 완료: {len(_ssg_details)}/{len(new_items)}건"
                )
                _add_job_log(
                    job.id,
                    f"[{site}] [{sf.name}] 상세 조회 완료: {len(_ssg_details):,}건",
                    job_type="collect",
                )
            # 상세 조회 성공한 상품만 저장 대상으로 사용 (없으면 검색 결과 그대로 사용)
            if _ssg_details:
                items_list = [
                    it
                    for it in items_list
                    if str(it.get("site_product_id", "")) in _ssg_details
                ]
            else:
                items_list = new_items

        # ABCmart/GrandStage: 저장 전 3건 병렬 선취합 (세션 배치 공유로 속도 향상)
        # LOTTEON(10건)/Nike(10건)/GSShop(20건)과 동일 패턴
        # a-rt.com 차단 방지: 3건 병렬 + 배치 간 0.5초 딜레이
        _abc_details: dict[str, dict[str, Any]] = {}
        if (
            site in ("ABCmart", "GrandStage")
            and client
            and hasattr(client, "get_detail")
        ):
            _new_items_abc = [
                it
                for it in items_list
                if str(it.get("site_product_id", "")) not in existing_ids
            ][:remaining]
            if _new_items_abc:
                _ABC_BATCH = 3
                logger.info(
                    f"[잡워커] {site} 선취합 시작: {len(_new_items_abc)}건 ({_ABC_BATCH}건 병렬)"
                )
                _add_job_log(
                    job.id,
                    f"[{site}] [{sf.name}] 상세 조회 시작: {len(_new_items_abc):,}건",
                    job_type="collect",
                )
                # 배치 단위로 세션 1개 획득 → 배치 내 모든 항목이 동일 JSESSIONID 재사용
                for _batch_start in range(0, len(_new_items_abc), _ABC_BATCH):
                    # 배치 시작 전 취소 체크 (배치당 3~5초 걸림)
                    from backend.domain.samba.emergency import (
                        clear_collect_cancel as _clear_cc,
                        is_collect_cancel_requested as _is_cc,
                        is_emergency_stopped as _is_es,
                    )

                    if _is_cc() or _is_es():
                        logger.info(f"[잡워커] {site} 선취합 취소: {job.id}")
                        try:
                            await repo.cancel_job(job.id)
                            await session.commit()
                        except Exception as _e:
                            logger.warning(
                                f"[잡워커] 취소 상태 저장 실패: {job.id} — {_e}"
                            )
                        _add_job_log(
                            job.id, f"[{site}] 수집 취소됨", job_type="collect"
                        )
                        _clear_cc()
                        return
                    _batch = _new_items_abc[_batch_start : _batch_start + _ABC_BATCH]
                    # 배치 전체가 공유할 세션 1개 획득
                    _batch_session = None
                    try:
                        _first_pid = str(_batch[0].get("site_product_id", ""))
                        _batch_session = await client._acquire_session_client(
                            _first_pid
                        )
                    except Exception as _se:
                        logger.warning(f"[잡워커] {site} 배치 세션 획득 실패: {_se!r}")
                    try:
                        _batch_details = await asyncio.gather(
                            *(
                                client.get_detail(
                                    str(it.get("site_product_id", "")),
                                    shared_client=_batch_session,
                                )
                                for it in _batch
                            ),
                            return_exceptions=True,
                        )
                    finally:
                        if _batch_session is not None:
                            try:
                                await _batch_session.aclose()
                            except Exception:
                                pass
                    for it, det in zip(_batch, _batch_details):
                        pid = str(it.get("site_product_id", ""))
                        if isinstance(det, Exception):
                            logger.warning(
                                f"[잡워커] {site} 선취합 실패 {pid}: {det!r}"
                            )
                            continue
                        if det:
                            _abc_details[pid] = det
                    _done_abc = min(_batch_start + _ABC_BATCH, len(_new_items_abc))
                    await repo.update_progress(job.id, _done_abc, len(_new_items_abc))
                    _add_job_log(
                        job.id,
                        f"[{site}] [{sf.name}] 상세 조회 [{_done_abc:,}/{len(_new_items_abc):,}]",
                        job_type="collect",
                    )
                    # 마지막 배치 제외 딜레이 (차단 방지)
                    if _batch_start + _ABC_BATCH < len(_new_items_abc):
                        await asyncio.sleep(0.5)
                logger.info(
                    f"[잡워커] {site} 선취합 완료: {len(_abc_details)}/{len(_new_items_abc)}건"
                )
                _add_job_log(
                    job.id,
                    f"[{site}] [{sf.name}] 상세 조회 완료: {len(_abc_details):,}건",
                    job_type="collect",
                )

        _collected_sold_out = 0
        _cancel_check_counter = 0
        for item in items_list:
            if total_saved >= remaining:
                break

            # 취소 확인 — 인메모리 플래그는 매 아이템, DB는 5건 단위
            from backend.domain.samba.emergency import (
                clear_collect_cancel,
                is_collect_cancel_requested,
                is_emergency_stopped,
            )

            if is_collect_cancel_requested() or is_emergency_stopped():
                logger.info(f"[잡워커] {site} 수집 취소됨: {job.id}")
                try:
                    await repo.cancel_job(job.id)
                    await session.commit()
                except Exception as _e:
                    logger.warning(f"[잡워커] 취소 상태 저장 실패: {job.id} — {_e}")
                _add_job_log(job.id, f"[{site}] 수집 취소됨", job_type="collect")
                clear_collect_cancel()
                return

            _cancel_check_counter += 1
            if _cancel_check_counter % 5 == 1:
                if await repo.is_cancelled(job.id):
                    logger.info(f"[잡워커] {site} 수집 취소됨: {job.id}")
                    try:
                        await repo.cancel_job(job.id)
                        await session.commit()
                    except Exception as _e:
                        logger.warning(f"[잡워커] 취소 상태 저장 실패: {job.id} — {_e}")
                    _add_job_log(job.id, f"[{site}] 수집 취소됨", job_type="collect")
                    return

            p_id = str(item.get("site_product_id", ""))
            if p_id in existing_ids:
                continue

            # 품절 필터링
            _item_sold_out = item.get("is_sold_out", False) or item.get(
                "isSoldOut", False
            )
            if _item_sold_out:
                if not _include_sold_out:
                    continue
                _collected_sold_out += 1

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
            _lotteon_cat4 = ""
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
                        _lotteon_cat4 = _parts[3] if len(_parts) > 3 else ""

            # 상세 페이지에서 추가 이미지/고시정보 보충
            detail = {}
            # LOTTEON: 선취합된 상세 데이터 사용
            if site == "LOTTEON" and p_id in _lotteon_details:
                detail = _lotteon_details[p_id]
            # Nike: 선취합된 상세 데이터 사용
            if site == "Nike" and p_id in _nike_details:
                detail = _nike_details[p_id]
            # GSShop: 선취합된 상세 데이터 사용
            if site == "GSShop" and p_id in _gsshop_details:
                detail = _gsshop_details[p_id]
            # SSG: 선취합된 상세 데이터 사용
            if site == "SSG" and p_id in _ssg_details:
                detail = _ssg_details[p_id]
            # ABCmart/GrandStage: 선취합된 상세 데이터 사용
            if site in ("ABCmart", "GrandStage") and p_id in _abc_details:
                detail = _abc_details[p_id]
            _skip_detail = _search_kwargs.get("_skip_detail", False)
            # ABCmart 최대혜택가: 선취합 미스 시 폴백 조회
            if (
                _use_max_discount
                and site in ("ABCmart", "GrandStage")
                and not _skip_detail
                and not detail
            ):
                if hasattr(client, "get_detail"):
                    try:
                        detail = await client.get_detail(p_id)
                    except Exception as e:
                        logger.warning(f"[잡워커] {site} 서버 상세 실패 {p_id}: {e}")
            if not _skip_detail and not detail:
                # 서버 HTTP 상세 조회 (선취합 미스 폴백)
                if hasattr(client, "get_detail"):
                    try:
                        # Nike: 검색 결과 URL 전달하여 중복 검색 방지
                        if site == "Nike":
                            detail = await client.get_detail(
                                p_id,
                                pdp_url=item.get("url") or item.get("source_url"),
                                base_info=item,
                            )
                        else:
                            detail = await client.get_detail(p_id)
                        # ABCmart/GrandStage: 선취합에서 누락된 경우이므로 sleep 불필요
                        if site not in ("ABCmart", "GrandStage"):
                            await asyncio.sleep(
                                0.15
                                if site == "Nike"
                                else (0 if site == "GSShop" else 0.3)
                            )
                    except Exception as e:
                        logger.warning(f"[잡워커] {site} 서버 상세 실패 {p_id}: {e}")

            # GSShop: 검색 결과에 이름/가격 없으므로 상세에서 보충
            # (선취합·폴백 상세조회 모두 거친 뒤 실행)
            if site == "GSShop" and detail:
                if not p_name or p_name == "(GSShop)":
                    p_name = detail.get("name", "") or p_name
                if sale_price <= 1:
                    sale_price = int(
                        detail.get("salePrice", 0)
                        or detail.get("bestBenefitPrice", 0)
                        or 0
                    )
                    original_price = (
                        int(detail.get("originalPrice", 0) or 0) or sale_price
                    )

            # 이미지: 확장앱 결과와 검색 API 중 더 많은 쪽 사용
            _detail_imgs = detail.get("images") or []
            _search_imgs = item.get("images", [])
            images = (
                _detail_imgs if len(_detail_imgs) > len(_search_imgs) else _search_imgs
            )
            # 원가: 최대혜택가 옵션 시 bestBenefitPrice 우선
            if _use_max_discount:
                _bbp = int(detail.get("bestBenefitPrice", 0) or 0) or int(
                    item.get("best_benefit_price", 0) or 0
                )
                cost = _bbp if _bbp > 0 else (int(item.get("cost", 0)) or sale_price)
            else:
                cost = int(item.get("cost", 0)) or sale_price
            # 배송비 원가 가산 (무료배송 아닌 경우)
            _sourcing_ship_fee = 0
            _is_free_ship = item.get("free_shipping", False) or detail.get(
                "free_shipping", False
            )
            if not _is_free_ship:
                _sourcing_ship_fee = int(detail.get("shipping_fee", 3000))
                cost += _sourcing_ship_fee
            _style_code = detail.get("style_code") or item.get("style_code", "")
            # Nike: scan(item)의 parse_subtitle이 더 구체적이므로 item 우선
            # 다른 소싱처: 기존 detail 우선 로직 유지
            if site == "Nike":
                _cat = item.get("category") or detail.get("category") or _category1_name
                _cat1 = item.get("category1") or detail.get("category1") or ""
                _cat2 = item.get("category2") or detail.get("category2") or ""
                _cat3 = item.get("category3") or detail.get("category3") or ""
                _cat4 = item.get("category4") or detail.get("category4") or ""
            elif site == "SSG":
                # SSG: 개별 상품의 전시카테고리 전체 경로 우선
                # category2가 없으면 leaf 단일명만 있는 불완전 카테고리이므로 ctgPath 폴백 사용
                _det_cat = detail.get("category", "")
                if _det_cat and detail.get("category2"):
                    _cat = _det_cat
                    _cat1 = detail.get("category1", "")
                    _cat2 = detail.get("category2", "")
                    _cat3 = detail.get("category3", "")
                    _cat4 = detail.get("category4", "")
                elif _ssg_cat:
                    _cat = _ssg_cat
                    _cat1 = _ssg_cat1
                    _cat2 = _ssg_cat2
                    _cat3 = _ssg_cat3
                    _cat4 = _ssg_cat4
                else:
                    _cat = item.get("category", "")
                    _cat1 = item.get("category1", "")
                    _cat2 = item.get("category2", "")
                    _cat3 = item.get("category3", "")
                    _cat4 = item.get("category4", "")
            else:
                _cat = (
                    detail.get("category")
                    or _lotteon_cat
                    or item.get("category", "")
                    or _category1_name  # 패션플러스: URL에서 재구성된 전체 카테고리 경로
                )
                _cat1 = (
                    detail.get("category1")
                    or _lotteon_cat1
                    or item.get("category1", "")
                    or _fp_cat1  # 패션플러스 URL의 category1Name
                )
                _cat2 = (
                    detail.get("category2")
                    or _lotteon_cat2
                    or item.get("category2", "")
                    or _fp_cat2  # 패션플러스 URL의 category2Name
                )
                _cat3 = (
                    detail.get("category3")
                    or _lotteon_cat3
                    or item.get("category3", "")
                    or _fp_cat3  # 패션플러스 URL의 category3Name
                )
                _cat4 = (
                    detail.get("category4")
                    or _lotteon_cat4
                    or item.get("category4", "")
                )
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
                "options": [
                    {
                        **o,
                        "stock": o.get("stock", 0)
                        if (o.get("stock") or 0) > 1
                        else (99 if (o.get("stock") or 0) > 0 else 0),
                    }
                    for o in (detail.get("options") or item.get("options", []))
                ],
                "category": _cat,
                "category1": _cat1,
                "category2": _cat2,
                "category3": _cat3,
                "category4": _cat4,
                "detail_html": detail.get("detail_html") or item.get("detail_html", ""),
                "detail_images": detail.get("detail_images")
                if len(detail.get("detail_images") or []) > len(images)
                else images,
                "material": detail.get("material", ""),
                "color": detail.get("color", ""),
                "manufacturer": detail.get("manufacturer") or item.get("brand", ""),
                "origin": detail.get("origin", ""),
                "sex": detail.get("sex", "") or "남녀공용",
                "season": detail.get("season", "") or "사계절",
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
                # 10건 단위 or 마지막 아이템 진행 로그 (== 로 정확히 1회만)
                if total_saved % 10 == 0 or total_saved == remaining:
                    _add_job_log(
                        job.id,
                        f"{_dprefix} [{sf.name}] [{existing_count + total_saved}/{requested_count}] 수집 중...",
                        job_type="collect",
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
                        "source_site_margins": pr.get("sourceSiteMargins", {}),
                    }
                count = await svc.apply_policy_to_filter_products(
                    filter_id, sf.applied_policy_id, policy_data
                )
                policy_msg = f", 정책 적용: {count}개"
            except Exception as e:
                logger.error(f"[잡워커] {site} 정책 전파 실패: {e}")

        _in_stock = total_saved - _collected_sold_out
        _parts = [f"신규 {total_saved}건"]
        if _in_stock > 0 or _collected_sold_out > 0:
            _parts.append(f"재고 {_in_stock}건 | 품절 {_collected_sold_out}건")
        if policy_msg:
            _parts.append(policy_msg.lstrip(", "))
        _add_job_log(
            job.id,
            f"{_dprefix} [{sf.name}] 수집 완료: {' | '.join(_parts)}",
            job_type="collect",
        )

        await repo.complete_job(
            job.id,
            {
                "saved": total_saved,
                "in_stock_count": _in_stock,
                "sold_out_count": _collected_sold_out,
            },
        )
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
