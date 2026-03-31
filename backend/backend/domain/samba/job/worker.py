"""백그라운드 잡 워커 — FastAPI lifespan에서 실행.

재시작 시 stuck running 잡 자동 복구 포함.
"""

import asyncio
import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
UTC = timezone.utc

# Job별 실시간 로그 버퍼 (인메모리, 최근 500줄)
_job_logs: dict[str, list[str]] = {}
_MAX_JOB_LOGS = 5000  # 인덱스 기반 since 폴링이므로 리스트 사용 (deque는 인덱스 어긋남)

def get_job_logs(job_id: str, since: int = 0) -> list[str]:
    """Job 로그 조회 (since 인덱스 이후)."""
    buf = _job_logs.get(job_id)
    if not buf:
        return []
    return buf[since:]

def _add_job_log(job_id: str, msg: str):
    """Job 로그 추가 (최대 _MAX_JOB_LOGS 유지)."""
    if job_id not in _job_logs:
        _job_logs[job_id] = []
    buf = _job_logs[job_id]
    buf.append(msg)
    if len(buf) > _MAX_JOB_LOGS:
        _job_logs[job_id] = buf[-_MAX_JOB_LOGS:]


def clear_job_logs(job_id: str):
    """완료된 잡 로그 삭제 — 메모리 해제."""
    _job_logs.pop(job_id, None)


def _run_collect_in_thread(worker: 'JobWorker', job_id: str, payload: dict):
    """별도 스레드에서 독립 이벤트 루프로 수집 실행."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(worker._execute_collect_isolated(job_id, payload))
    except Exception as e:
        logger.error(f"[잡워커] 수집 스레드 에러: {job_id} — {e}")
    finally:
        loop.close()


def _run_transmit_in_thread(worker: 'JobWorker', job_id: str, payload: dict):
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

    def __init__(self):
        self._running = True
        self._active_types: set[str] = set()  # 현재 실행 중인 잡 타입

    async def start(self):
        """무한 루프: pending 잡 조회 → 타입별 병렬 실행."""
        logger.info("[잡워커] 시작 (병렬 모드: collect/transmit 동시 실행)")
        # 배포/재시작으로 stuck된 running 잡 자동 복구
        try:
            from backend.db.orm import get_write_session
            from backend.domain.samba.job.repository import SambaJobRepository
            async with get_write_session() as session:
                repo = SambaJobRepository(session)
                recovered = await repo.recover_stuck_running()
                if recovered:
                    logger.info(f"[잡워커] stuck running 잡 {recovered}건 → pending 복구")
        except Exception as e:
            logger.warning(f"[잡워커] stuck 잡 복구 실패: {e}")
        while self._running:
            try:
                executed = await self._poll_once()
                if not executed:
                    await asyncio.sleep(self.POLL_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[잡워커] 폴링 에러: {e}")
                await asyncio.sleep(self.POLL_INTERVAL)
        logger.info("[잡워커] 종료")

    def stop(self):
        self._running = False

    async def _poll_once(self) -> bool:
        """pending 잡을 타입별로 1개씩 병렬 실행. 같은 타입은 순차."""
        from backend.db.orm import get_write_session
        from backend.domain.samba.job.repository import SambaJobRepository

        async with get_write_session() as session:
            repo = SambaJobRepository(session)
            jobs = await repo.list_pending(limit=5)
            if not jobs:
                return False

            # 실행 중이 아닌 타입의 잡만 선택 (타입별 1개)
            to_run = []
            for job in jobs:
                if job.job_type not in self._active_types:
                    to_run.append(job)
                    self._active_types.add(job.job_type)
                else:
                    # 실행 안 할 잡은 pending으로 되돌림
                    job.status = "pending"
                    job.started_at = None
            if not to_run:
                # 전부 되돌림
                await session.commit()
                return False

            # running 상태를 DB에 커밋 → 다음 폴링에서 중복 선택 방지
            await session.commit()

        # 선택된 잡들 병렬 실행 (각각 독립 세션)
        if len(to_run) == 1:
            await self._execute_job(to_run[0])
        else:
            await asyncio.gather(*[self._execute_job(j) for j in to_run], return_exceptions=True)
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
                    await asyncio.sleep(2)
                    elapsed += 2
                if thread.is_alive():
                    logger.error(f"[잡워커] 수집 스레드 10분 타임아웃: {_job_id}")
                    _add_job_log(_job_id, f"수집 타임아웃 (10분)")
                return

            # 전송 + 기타: 메인 루프 직접 실행 (인메모리 로그 공유)
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
                    except Exception:
                        pass
        finally:
            self._active_types.discard(_job_type)
            clear_job_logs(_job_id)

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
                    except Exception:
                        pass
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
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"[잡워커] 전송 세션 에러: {job_id} — {e}")
    async def _run_transmit(self, job, repo, session):
        """전송 잡 실행 — 기존 shipment_service 호출."""
        from backend.domain.samba.shipment.service import SambaShipmentService, is_cancel_requested
        from backend.domain.samba.shipment.repository import SambaShipmentRepository

        payload = job.payload or {}
        product_ids = payload.get("product_ids", [])
        update_items = payload.get("update_items", [])
        target_account_ids = payload.get("target_account_ids", [])
        skip_unchanged = payload.get("skip_unchanged", False)

        if not product_ids:
            await repo.fail_job(job.id, "product_ids 없음")
            return

        svc = SambaShipmentService(SambaShipmentRepository(session), session)
        total = len(product_ids)
        await repo.update_progress(job.id, 0, total)

        # 상품명 조회 캐시
        from backend.domain.samba.collector.repository import SambaCollectedProductRepository
        cp_repo = SambaCollectedProductRepository(session)

        results = []
        success_count = 0
        fail_count = 0
        failed_pids: list[str] = []  # 재시도 대상

        # 계정명 조회용
        from backend.domain.samba.account.repository import SambaMarketAccountRepository
        acc_repo = SambaMarketAccountRepository(session)

        # 상품별 전송 루프
        for i, pid in enumerate(product_ids):
            # 비상정지 + Job 취소 체크 (건별)
            from backend.domain.samba.emergency import is_emergency_stopped
            if is_emergency_stopped() or await repo.is_cancelled(job.id):
                cancelled = len(product_ids) - i
                reason = "비상정지" if is_emergency_stopped() else "취소"
                _add_job_log(job.id, f"{reason} — {i}건 완료, {cancelled}건 중단")
                logger.info(f"[잡워커] 전송 {reason}: {job.id} — {i}건 완료, {cancelled}건 중단")
                await repo.fail_job(job.id, f"{reason}: {i}건 완료, {cancelled}건 중단")
                return
            prod = await cp_repo.get_async(pid)
            site_pid = prod.site_product_id if prod else ""
            # 등록상품명 조합: [브랜드] 상품명 스타일코드
            _brand = (prod.brand or "") if prod else ""
            _style = (prod.style_code or "") if prod else ""
            _raw_name = (prod.name or "") if prod else pid[-8:]
            prod_name = f"{_brand} {_raw_name}".strip()[:35]
            if _style:
                prod_name = f"{prod_name} {_style}"
            if site_pid:
                prod_name = f"{prod_name} ({site_pid})"
            try:
                result = await svc.start_update(
                    [pid], update_items, target_account_ids,
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
                    acc_label = f"{acc.market_name}({acc.seller_id or acc.business_name or '-'})" if acc else acc_id
                    pno = r.get("product_nos", {}).get(acc_id, "")
                    ur = r.get("update_result", {})
                    rl = f" [{ur.get('refresh', '')}]" if isinstance(ur, dict) and ur.get("refresh") else ""
                    if acc_status == "success":
                        any_success = True
                        success_count += 1
                        _add_job_log(job.id, f"[{i+1}/{total}] {prod_name} → {acc_label}: 전송{rl}")
                    elif acc_status == "skipped":
                        _add_job_log(job.id, f"[{i+1}/{total}] {prod_name} → {acc_label}: 스킵{rl}")
                    else:
                        fail_count += 1
                        err = str(tx_error.get(acc_id, "실패"))[:60]
                        if "<asyncio" in err or "Semaphore" in err:
                            err = "전송 동시성 오류"
                        _add_job_log(job.id, f"[{i+1}/{total}] {prod_name} → {acc_label}: {err}")
                if not tx_result:
                    if status == "skipped":
                        refresh_info = r.get("update_result", {})
                        rl = refresh_info.get("refresh", "") if isinstance(refresh_info, dict) else ""
                        _add_job_log(job.id, f"[{i+1}/{total}] {prod_name}: 스킵 [{rl}]")
                    elif r.get("error") or tx_error.get("_all"):
                        fail_count += 1
                        err_msg = r.get("error") or tx_error.get("_all", "실패")
                        _add_job_log(job.id, f"[{i+1}/{total}] {prod_name}: {str(err_msg)[:60]}")
                    else:
                        fail_count += 1
                        _add_job_log(job.id, f"[{i+1}/{total}] {prod_name}: 실패")
                # 1차 실패 → 재시도 대상
                if not any_success and status not in ("skipped", "completed"):
                    failed_pids.append(pid)
                results.append(result)
            except Exception as e:
                fail_count += 1
                _add_job_log(job.id, f"[{i+1}/{total}] {prod_name}: {e}")
                results.append({"error": str(e)})
                failed_pids.append(pid)
            await repo.update_progress(job.id, i + 1, total)
            # 건별 커밋 — 세션 점유 최소화 + 중간 결과 보존
            await session.commit()

        # 2차 재시도 — 실패 상품만
        retry_success = 0
        if failed_pids:
            _add_job_log(job.id, f"재시도 시작 — 실패 {len(failed_pids)}건")
            await asyncio.sleep(3)  # 세마포어 해제 대기
            for ri, pid in enumerate(failed_pids):
                from backend.domain.samba.emergency import is_emergency_stopped
                if is_emergency_stopped() or await repo.is_cancelled(job.id):
                    break
                prod = await cp_repo.get_async(pid)
                site_pid = prod.site_product_id if prod else ""
                prod_name = (prod.name[:30] if prod and prod.name else pid[-8:])
                if site_pid:
                    prod_name = f"{prod_name} ({site_pid})"
                try:
                    prev_fail = fail_count
                    result = await svc.start_update(
                        [pid], update_items, target_account_ids,
                        skip_unchanged=skip_unchanged,
                    )
                    r2 = (result.get("results", []) or [{}])[0]
                    tx2 = r2.get("transmit_result", {})
                    any_ok = any(s == "success" for s in tx2.values())
                    if any_ok:
                        retry_success += 1
                        fail_count = prev_fail - 1
                        _add_job_log(job.id, f"[재시도 {ri+1}/{len(failed_pids)}] {prod_name}: 복구")
                    else:
                        _add_job_log(job.id, f"[재시도 {ri+1}/{len(failed_pids)}] {prod_name}: 재실패")
                except Exception as e:
                    _add_job_log(job.id, f"[재시도 {ri+1}/{len(failed_pids)}] {prod_name}: {e}")
                await session.commit()
            if retry_success > 0:
                _add_job_log(job.id, f"재시도 완료 — {retry_success}/{len(failed_pids)}건 복구")

        final_fail = fail_count
        _add_job_log(job.id, f"전송 완료 — 성공 {success_count}건, 실패 {final_fail}건")
        await repo.complete_job(job.id, {"success": success_count, "failed": final_fail})
        logger.info(f"[잡워커] 전송 완료: {job.id} (성공 {success_count}/{total}건)")


    async def _run_collect(self, job, repo, session):
        """수집 잡 실행 — collector_collection의 _stream_musinsa 로직 이식."""
        from urllib.parse import urlparse, parse_qs
        from sqlmodel import select, func as _func
        from backend.domain.samba.collector.model import SambaSearchFilter
        from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
        from backend.domain.samba.proxy.musinsa import MusinsaClient, RateLimitError
        from backend.domain.samba.forbidden.model import SambaSettings
        from backend.api.v1.routers.samba.collector_common import _build_product_data
        from backend.domain.samba.collector.refresher import _site_intervals, _site_consecutive_errors, get_interval_key
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
        DIRECT_API_SITES = {"FashionPlus", "Nike", "Adidas"}
        # 확장앱 기반 소싱처 (소싱큐)
        EXTENSION_SITES = {"ABCmart", "GrandStage", "OKmall", "LOTTEON", "GSShop", "ElandMall", "SSF", "SSG"}

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
            logger.info(f"[잡워커] 수집 프록시: {_collect_proxy.split('@')[-1] if '@' in _collect_proxy else 'on'}")

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
        count_stmt = select(_func.count()).where(
            CPModel.search_filter_id == filter_id
        )
        existing_count = (await session.execute(count_stmt)).scalar() or 0
        remaining = max(0, requested_count - existing_count)

        if remaining <= 0:
            await repo.complete_job(job.id, {
                "saved": 0,
                "message": f"이미 {existing_count}개 수집됨 (요청: {requested_count}개)",
            })
            return

        await repo.update_progress(job.id, existing_count, requested_count)

        # 수집 루프
        total_saved = 0
        total_skipped = 0
        search_page = 1

        while total_saved < remaining and search_page <= 20:
            # 취소 확인 (DB에서 상태 재조회)
            from backend.domain.samba.job.model import SambaJob as _SJ
            _job_check = await session.get(_SJ, job.id)
            if _job_check and _job_check.status == "failed":
                logger.info(f"[잡워커] 수집 취소됨: {job.id}")
                return

            # 검색
            try:
                data = await client.search_products(
                    keyword=keyword, page=search_page, size=100,
                    category=_category_filter,
                    brand=_brand_filter,
                    min_price=_min_price,
                    max_price=_max_price,
                    gf=_gf_filter,
                )
                search_items = data.get("data", [])
                logger.info(f"[잡워커] 검색 p{search_page}: {len(search_items)}건 (kw={keyword}, brand={_brand_filter})")
                if not search_items:
                    break
                await asyncio.sleep(_site_intervals.get(_ik, 0))
            except Exception as e:
                logger.error(f"[잡워커] 검색 실패: {e}")
                break

            # 중복 필터링
            candidate_ids = [str(item.get("siteProductId", item.get("goodsNo", ""))) for item in search_items]
            existing_result = await session.execute(
                select(CPModel.site_product_id).where(
                    CPModel.source_site == "MUSINSA",
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

            logger.info(f"[잡워커] 중복={len(existing_ids)}, 타겟={len(targets)}, 스킵={total_skipped}")
            if not targets:
                # 연속 3페이지 신규 0건이면 조기 종료 (나머지도 중복일 가능성 높음)
                _empty_pages = getattr(self, '_empty_pages', 0) + 1
                self._empty_pages = _empty_pages
                if _empty_pages >= 3:
                    logger.info(f"[잡워커] 연속 {_empty_pages}페이지 신규 0건 → 조기 종료")
                    break
                search_page += 1
                continue
            self._empty_pages = 0  # 신규 상품 발견 시 카운터 리셋

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
                        detail = await client.get_goods_detail(goods_no, _shared_client=_shared_http)
                        if not detail or not detail.get("name"):
                            return None
                        if detail.get("saleStatus") == "sold_out" or detail.get("isOutOfStock"):
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
                        _site_consecutive_errors[_ik] = _site_consecutive_errors.get("MUSINSA", 0) + 1
                        if _site_consecutive_errors[_ik] >= 5:
                            _rate_limited = True
                        if rle.retry_after > 0:
                            await asyncio.sleep(rle.retry_after)
                        return None
                    except Exception as e:
                        logger.warning(f"[잡워커] 수집 실패 {goods_no}: {e}")
                        return None

            _collect_results = await asyncio.gather(*[_fetch_detail(gn) for gn in targets])
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
                    new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else (detail.get("salePrice") or 0)
                else:
                    new_cost = detail.get("salePrice") or 0

                raw_cat = detail.get("category", "") or ""
                cat_parts = [c.strip() for c in raw_cat.split(">") if c.strip()] if raw_cat else []
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
                    detail, goods_no, filter_id, "MUSINSA",
                    new_cost, _sale_price, _original_price,
                    raw_cat, cat_parts, raw_detail_html,
                )
                await svc.create_collected_product(product_data)
                total_saved += 1
                await repo.update_progress(job.id, existing_count + total_saved, requested_count)

                if total_saved >= remaining:
                    break

            search_page += 1

        # 수집 완료 → last_collected_at 갱신 + 요청수를 실제 수집수로 보정
        from sqlalchemy import update as _sa_upd
        _actual = (await session.execute(
            select(_func.count()).where(CPModel.search_filter_id == filter_id)
        )).scalar() or 0
        _upd_vals: dict = {"last_collected_at": datetime.now(UTC)}
        if _actual > 0:
            _upd_vals["requested_count"] = _actual
        await session.execute(_sa_upd(SambaSearchFilter).where(SambaSearchFilter.id == filter_id).values(**_upd_vals))

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
                    }
                count = await svc.apply_policy_to_filter_products(
                    filter_id, sf.applied_policy_id, policy_data
                )
                policy_msg = f"정책 적용: {count}개"
            except Exception as e:
                logger.error(f"[잡워커] 정책 전파 실패: {e}")

        await repo.complete_job(job.id, {
            "saved": total_saved,
            "skipped": total_skipped,
            "policy": policy_msg,
        })
        logger.info(f"[잡워커] 수집 완료: {job.id} ({total_saved}건)")

    async def _collect_direct_api(self, job, sf, session, repo):
        """FashionPlus/Nike/Adidas 등 직접 API 소싱처 수집."""
        from sqlalchemy import func as _func, select
        from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
        from backend.api.v1.routers.samba.collector_common import _get_services, generate_group_key

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
                keyword = qs.get("searchWord", [keyword])[0]
                # 패션플러스 필터 파라미터
                for k in ("category1Id", "category2Id", "category3Id", "sort", "minPrice", "maxPrice"):
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
            await repo.complete_job(job.id, {"saved": 0, "message": f"이미 {existing_count}개 수집됨"})
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

        # 확장앱 소싱큐 기반 사이트 — 소싱큐로 검색 요청
        if not client:
            from backend.domain.samba.proxy.sourcing_queue import SourcingQueue, SITE_SEARCH_URLS
            if site not in SITE_SEARCH_URLS:
                await repo.fail_job(job.id, f"미지원 소싱처: {site}")
                return
            try:
                _req_id, _future = SourcingQueue.add_search_job(site, keyword)
                ext_result = await asyncio.wait_for(_future, timeout=60)
                items_list = ext_result.get("products", [])
                logger.info(f"[잡워커] {site} 확장앱 검색 '{keyword}' → {len(items_list)}건")
            except asyncio.TimeoutError:
                SourcingQueue.resolvers.pop(_req_id, None)
                await repo.fail_job(job.id, f"확장앱 응답 타임아웃. 확장앱이 실행 중인지 확인하세요.")
                return
            except Exception as e:
                await repo.fail_job(job.id, f"확장앱 검색 실패: {e}")
                return
            # 확장앱 결과는 검색 API와 동일 포맷으로 처리 (아래 중복필터+저장 로직 공유)
            result = {"products": items_list, "total": len(items_list)}

        else:
            # 직접 API 검색
            try:
                result = await client.search(keyword, max_count=max(remaining * 2, 100), **_search_kwargs)
                items_list = result.get("products", [])
                logger.info(f"[잡워커] {site} 검색 '{keyword}' → {len(items_list)}건")
            except Exception as e:
                await repo.fail_job(job.id, f"검색 실패: {e}")
                return

        await repo.update_progress(job.id, 0, remaining)

        # 카테고리 매핑 (패션플러스)
        _category1_name = ""
        if site == "FashionPlus" and _search_kwargs.get("category1Id"):
            from backend.domain.samba.proxy.fashionplus import _CATEGORY_MAP
            _category1_name = _CATEGORY_MAP.get(_search_kwargs["category1Id"], "")

        # 중복 필터링
        candidate_ids = [str(item.get("site_product_id", "")) for item in items_list if item.get("site_product_id")]
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

        for item in items_list:
            if total_saved >= remaining:
                break

            # 취소 확인 (DB에서 상태 재조회)
            from backend.domain.samba.job.model import SambaJob as _SJ2
            _job_chk = await session.get(_SJ2, job.id)
            if _job_chk and _job_chk.status == "failed":
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

            # 상세 페이지에서 추가 이미지/고시정보 보충 (서버 HTTP 우선)
            detail = {}
            _skip_detail = _search_kwargs.get("_skip_detail", False)
            if not _skip_detail:
                # 서버 HTTP 상세 조회 (빠르고 안정적)
                if hasattr(client, 'get_detail'):
                    try:
                        detail = await client.get_detail(p_id)
                        await asyncio.sleep(0.3)
                    except Exception as e:
                        logger.warning(f"[잡워커] {site} 서버 상세 실패 {p_id}: {e}")

            # 이미지: 확장앱 결과와 검색 API 중 더 많은 쪽 사용
            _detail_imgs = detail.get("images") or []
            _search_imgs = item.get("images", [])
            images = _detail_imgs if len(_detail_imgs) > len(_search_imgs) else _search_imgs
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
                "source_url": item.get("source_url", "") or detail.get("source_url", ""),
                "name": p_name,
                "brand": item.get("brand", ""),
                "original_price": original_price,
                "sale_price": sale_price,
                "cost": cost,
                "images": images,
                "options": detail.get("options") or item.get("options", []),
                "category": detail.get("category") or item.get("category", "") or _category1_name,
                "category1": detail.get("category1") or item.get("category1", ""),
                "category2": detail.get("category2") or item.get("category2", ""),
                "category3": detail.get("category3") or item.get("category3", ""),
                "detail_html": detail.get("detail_html") or item.get("detail_html", ""),
                "detail_images": detail.get("detail_images") if len(detail.get("detail_images") or []) > len(images) else images,
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
                ) or f"fp_{site.lower()}_{p_id}",
                "price_history": [{
                    "date": datetime.now(UTC).isoformat(),
                    "sale_price": sale_price,
                    "original_price": original_price,
                    "cost": cost,
                    "options": detail.get("options") or item.get("options", []),
                }],
            }
            try:
                await svc.create_collected_product(product_data)
                total_saved += 1
                await repo.update_progress(job.id, existing_count + total_saved, requested_count)
            except Exception as e:
                logger.warning(f"[잡워커] {site} 저장 실패 {p_id}: {e}")

        # last_collected_at 갱신 + 요청수를 실제 수집수로 보정 (카테고리 중복 제거)
        from sqlalchemy import update as sa_update
        actual_count = (await session.execute(
            select(_func.count()).where(CPModel.search_filter_id == filter_id)
        )).scalar() or 0
        update_vals: dict = {"last_collected_at": datetime.now(UTC)}
        if actual_count > 0:
            update_vals["requested_count"] = actual_count
        from backend.domain.samba.collector.model import SambaSearchFilter as _SF
        await session.execute(sa_update(_SF).where(_SF.id == filter_id).values(**update_vals))

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
                    }
                count = await svc.apply_policy_to_filter_products(
                    filter_id, sf.applied_policy_id, policy_data
                )
                policy_msg = f", 정책 적용: {count}개"
            except Exception as e:
                logger.error(f"[잡워커] {site} 정책 전파 실패: {e}")

        await repo.complete_job(job.id, {"saved": total_saved})
        logger.info(f"[잡워커] {site} 수집 완료: {job.id} ({total_saved}건{policy_msg})")

    async def _run_stub(self, job, repo, name: str):
        """미구현 잡 타입 스텁."""
        logger.info(f"[잡워커] {name} 잡은 아직 미구현: {job.id}")
        await repo.complete_job(job.id, {"message": f"{name} 잡 미구현 — 추후 지원"})
