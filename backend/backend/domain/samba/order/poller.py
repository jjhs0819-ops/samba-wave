"""주문 자동 폴링 — 새 주문 감지 시 자동 동기화 (8~24시) 또는 카카오톡 알림 발송."""

import asyncio
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

ORDER_POLL_INTERVAL = int(os.environ.get("ORDER_POLL_INTERVAL_SECONDS", str(30 * 60)))
KST = timezone(timedelta(hours=9))


async def _fetch_new_order_numbers() -> tuple[dict[str, list[str]], set[str | None]]:
    """각 마켓 계정에서 최근 1일치 주문 번호를 조회하고, DB에 없는 신규 건만 반환.

    Returns:
        (new_by_market, tenant_ids_with_new_orders)

    [2026-06-30] 세션 미점유 리팩토링: 과거엔 write 세션을 열어둔 채 모든 마켓 API 를
    순차 호출 → 세션 최대 542초 점유로 write 풀 고갈 + api 단일워커 이벤트루프 142초
    블로킹(헬스 실패, 무신사 코디 658초 무진척→좀비화 연쇄)의 근본 원인. 이제 DB 조회
    (계정 목록 / 롯데홈 자격증명 / 신규판정)만 그때그때 짧은 read 세션으로 감싸고,
    느린 마켓 API 호출 동안에는 DB 세션을 전혀 점유하지 않는다. 이 함수는 SELECT 만 한다.
    """
    from sqlalchemy import text as _text
    from sqlmodel import select

    from backend.db.orm import get_read_session
    from backend.domain.samba.account.model import SambaMarketAccount

    async with get_read_session() as _acc_session:
        result = await _acc_session.exec(
            select(SambaMarketAccount).where(SambaMarketAccount.is_active == True)  # noqa: E712
        )
        accounts = result.all()

    new_by_market: dict[str, list[str]] = defaultdict(list)
    tenant_ids_with_new: set[str | None] = set()

    for account in accounts:
        market_type = account.market_type
        extras = account.additional_fields or {}
        label = account.market_name or market_type

        try:
            raw_order_numbers: list[str] = []

            if market_type == "smartstore":
                from backend.domain.samba.proxy.smartstore import SmartStoreClient

                client_id = extras.get("clientId", "") or account.api_key or ""
                client_secret = (
                    extras.get("clientSecret", "") or account.api_secret or ""
                )
                if not client_id or not client_secret:
                    continue
                client = SmartStoreClient(client_id, client_secret)
                raw_orders = await client.get_orders(days=1)
                for ro in raw_orders:
                    po = ro.get("productOrder", ro)
                    oid = po.get("productOrderId", "")
                    if oid:
                        raw_order_numbers.append(oid)

            elif market_type == "lotteon":
                from backend.domain.samba.proxy.lotteon import LotteonClient

                api_key = extras.get("apiKey", "") or account.api_key or ""
                if not api_key:
                    continue
                client = LotteonClient(api_key)
                await client.test_auth()
                raw_orders = await client.get_orders(days=7)
                for ro in raw_orders:
                    od_no = str(ro.get("odNo", "") or "")
                    od_seq = ro.get("odSeq", 1) or 1
                    oid = f"{od_no}_{od_seq}" if od_no else ""
                    if oid:
                        raw_order_numbers.append(oid)

            elif market_type == "playauto":
                from datetime import UTC, datetime, timedelta

                from backend.domain.samba.proxy.playauto import PlayAutoClient

                api_key = extras.get("apiKey", "") or account.api_key or ""
                if not api_key:
                    continue
                start_date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y%m%d")
                client = PlayAutoClient(api_key)
                try:
                    raw_orders = await client.get_orders(
                        start_date=start_date, count=200
                    )
                    for ro in raw_orders:
                        oid = str(ro.get("OrderCode", "") or "")
                        if oid:
                            raw_order_numbers.append(oid)
                finally:
                    await client.close()

            elif market_type == "lottehome":
                from datetime import UTC, datetime, timedelta

                from backend.domain.samba.forbidden.model import SambaSettings
                from backend.domain.samba.proxy.lottehome import LotteHomeClient

                async with get_read_session() as _lh_session:
                    _lh_creds_result = await _lh_session.exec(
                        select(SambaSettings).where(
                            SambaSettings.key == "lottehome_credentials"
                        )
                    )
                    _lh_creds_row = _lh_creds_result.first()
                    lh_creds = _lh_creds_row.value if _lh_creds_row else {}

                lh_user_id = (
                    lh_creds.get("userId", "")
                    or extras.get("userId", "")
                    or account.seller_id
                    or ""
                )
                lh_password = (
                    lh_creds.get("password", "") or extras.get("password", "") or ""
                )
                lh_agnc_no = lh_creds.get("agncNo", "") or extras.get("agncNo", "")
                lh_env = lh_creds.get("env", "prod")

                if not lh_user_id or not lh_password:
                    continue

                from backend.domain.samba.collector.refresher import (
                    get_collect_proxy_url,
                )

                _lh_proxy = get_collect_proxy_url()
                lh_client = LotteHomeClient(
                    lh_user_id, lh_password, lh_agnc_no, lh_env, proxy_url=_lh_proxy
                )
                if _lh_proxy:
                    logger.info(
                        f"[주문폴러] 롯데홈쇼핑 collect 프록시 적용: {_lh_proxy.split('@')[-1] if '@' in _lh_proxy else 'on'}"
                    )
                lh_end = datetime.now(UTC)
                lh_start = lh_end - timedelta(days=1)
                lh_start_str = lh_start.strftime("%Y%m%d")
                lh_end_str = lh_end.strftime("%Y%m%d")
                try:
                    for sel_option in ["01", "02", "03"]:
                        try:
                            lh_orders = await lh_client.search_new_orders(
                                lh_start_str, lh_end_str, sel_option=sel_option
                            )
                        except Exception as _lh_e:
                            # 0001=데이터없음 포함 — 한 sel_option 실패가 나머지 차단 방지
                            logger.warning(
                                "[주문폴러] %s: search_new_orders sel=%s 실패(계속): %s",
                                label,
                                sel_option,
                                _lh_e,
                            )
                            lh_orders = []
                        for ro in lh_orders:
                            prod = (
                                ro.get("ProdInfo", {})
                                if isinstance(ro.get("ProdInfo"), dict)
                                else {}
                            )
                            oid = str(
                                ro.get("SubOrdNo")
                                or prod.get("DlvUnitSn")
                                or prod.get("OrdDtlSn")
                                or ro.get("OrdNo", "")
                                or ""
                            )
                            if oid:
                                raw_order_numbers.append(oid)
                finally:
                    pass  # LotteHomeClient는 per-request httpx — close 불필요

            elif market_type == "poison":
                from backend.domain.samba.proxy.poison import PoisonClient

                app_key = (
                    extras.get("app_key", "")
                    or extras.get("appKey", "")
                    or account.api_key
                    or ""
                )
                app_secret = (
                    extras.get("app_secret", "")
                    or extras.get("appSecret", "")
                    or account.api_secret
                    or ""
                )
                if not app_key or not app_secret:
                    continue
                client = PoisonClient(app_key, app_secret)
                raw_orders = await client.get_orders(days=7)
                for ro in raw_orders:
                    oid = str(ro.get("order_no", "") or "")
                    if oid:
                        raw_order_numbers.append(oid)

            else:
                continue

            if not raw_order_numbers:
                continue

            # DB에 이미 있는 order_number 필터링 (짧은 read 세션 — API 호출 중엔 미점유)
            async with get_read_session() as _chk_session:
                rows = await _chk_session.execute(
                    _text(
                        "SELECT order_number FROM samba_order "
                        "WHERE order_number = ANY(:nums) AND channel_id = :cid"
                    ),
                    {"nums": raw_order_numbers, "cid": account.id},
                )
                existing = {r[0] for r in rows}
            fresh = [n for n in raw_order_numbers if n not in existing]

            if fresh:
                new_by_market[label].extend(fresh)
                tenant_ids_with_new.add(account.tenant_id)
                logger.info("[주문폴러] %s: 신규 주문 %d건 감지", label, len(fresh))

        except Exception as exc:
            logger.warning("[주문폴러] %s 조회 실패: %s", label, exc)

    return dict(new_by_market), tenant_ids_with_new


async def _enqueue_order_sync_jobs(tenant_ids: set[str | None]) -> None:
    """신규 주문 감지 → 테넌트별 order_sync 잡 발행 (전송 전용 워커 B가 처리).

    [2026-06-26] 기존 _run_direct_order_sync 는 api 프로세스 이벤트루프에서
    sync_orders_from_markets + auto_check_order_issues(refresh_products_bulk 의
    수백개 task swarm)를 직접 돌려 단일 워커 루프를 1~3초씩 막았다 →
    '백엔드 서버 연결 실패' 근본 원인. 이를 order_sync 잡으로 위임해 api 루프를
    비운다. 역마진/재고없음 자동판정(auto_check_order_issues)은 order_sync
    핸들러 말미(payload.source == 'order_poller')에서 B 워커가 실행한다.
    """
    from sqlmodel import col, select

    from backend.db.orm import get_write_session
    from backend.domain.samba.job.model import (
        JobStatus,
        SambaJob,
        generate_job_id,
    )

    async with get_write_session() as session:
        for tenant_id in tenant_ids:
            # 같은 테넌트의 order_sync 잡이 이미 대기/실행 중이면 중복 발행 안 함
            existing = (
                (
                    await session.execute(
                        select(SambaJob)
                        .where(
                            SambaJob.job_type == "order_sync",
                            col(SambaJob.status).in_(
                                [JobStatus.PENDING, JobStatus.RUNNING]
                            ),
                            SambaJob.tenant_id == tenant_id,
                        )
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
            if existing:
                logger.info(
                    "[주문폴러] order_sync 잡 이미 진행 중 (tenant=%s, job=%s) — 스킵",
                    tenant_id,
                    existing.id,
                )
                continue
            job = SambaJob(
                id=generate_job_id(),
                tenant_id=tenant_id,
                job_type="order_sync",
                payload={"days": 7, "source": "order_poller"},
            )
            session.add(job)
            await session.flush()
            logger.info(
                "[주문폴러] order_sync 잡 발행 (tenant=%s, job=%s)", tenant_id, job.id
            )
        # get_write_session 은 정상 종료 시 auto-commit 안 함 → 명시적 commit 필수
        await session.commit()


async def _create_cs_sync_job(session, tenant_id: str | None) -> None:
    """cs_sync 잡 생성 (중복 실행 방지 포함)."""
    from sqlmodel import col, select

    from backend.domain.samba.job.model import JobStatus, SambaJob, generate_job_id

    active = (
        (
            await session.execute(
                select(SambaJob)
                .where(
                    SambaJob.job_type == "cs_sync",
                    col(SambaJob.status).in_([JobStatus.PENDING, JobStatus.RUNNING]),
                    SambaJob.tenant_id == tenant_id,
                )
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if active:
        logger.info(
            "[주문폴러] cs_sync 잡 이미 실행 중 (tenant=%s, job=%s)",
            tenant_id,
            active.id,
        )
        return

    job = SambaJob(
        id=generate_job_id(),
        tenant_id=tenant_id,
        job_type="cs_sync",
        payload={},
    )
    session.add(job)
    await session.flush()
    # get_write_session 은 정상 종료 시 auto-commit 하지 않음(orm.py:212) — flush만 하면
    # 블록 종료 때 INSERT가 롤백돼 cs_sync 잡이 영영 생성되지 않는다(CS 자동수집 전면 정지).
    # 반드시 명시적으로 commit.
    await session.commit()
    logger.info("[주문폴러] cs_sync 잡 생성 (tenant=%s, job=%s)", tenant_id, job.id)


async def start_order_poller() -> None:
    """백그라운드 주문 폴링 루프 (lifecycle.py에서 asyncio.create_task로 실행)."""
    from backend.utils.kakao_notify import send_kakao_message

    # 서버 완전 기동 대기
    await asyncio.sleep(60)
    logger.info("[주문폴러] 시작 (간격: %d초)", ORDER_POLL_INTERVAL)

    while True:
        try:
            now_kst = datetime.now(KST)
            is_night = 0 <= now_kst.hour < 8  # 0~8시 제외

            # _fetch_new_order_numbers 가 자체적으로 짧은 read 세션만 쓰므로(마켓 API
            # 호출 중 세션 미점유), 여기서 write 세션을 542초 잡던 문제 제거.
            new_by_market, tenant_ids = await _fetch_new_order_numbers()

            # CS 문의 동기화는 주문 자동수집 루프(lifecycle._order_auto_sync_loop)로
            # 이관됨 — 여기 30분 폴러에서는 더 이상 cs_sync 잡을 만들지 않는다.

            if new_by_market and not is_night:
                # api 루프 블로킹 방지 — 직접 동기화 대신 전송워커(B)에 order_sync 잡 위임
                # (구 _run_direct_order_sync 인라인 경로 제거, 2026-06-26)
                await _enqueue_order_sync_jobs(tenant_ids)

            if new_by_market:
                total = sum(len(v) for v in new_by_market.values())
                lines = [f"🛒 새 주문 {total}건 감지"]
                for market, nums in new_by_market.items():
                    lines.append(f"  {market}: {len(nums)}건")

                if is_night:
                    lines.append("\n동기화 버튼을 눌러 주문을 확인하세요.")
                else:
                    lines.append("\n자동 동기화를 시작했습니다.")

                await send_kakao_message("\n".join(lines))

        except asyncio.CancelledError:
            logger.info("[주문폴러] 종료")
            return
        except Exception as exc:
            logger.warning("[주문폴러] 오류 발생: %s", exc)

        await asyncio.sleep(ORDER_POLL_INTERVAL)
