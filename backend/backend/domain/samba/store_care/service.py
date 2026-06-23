"""스토어케어 서비스."""

import math

from .model import StoreCareSchedule, StoreCarePurchase, StoreCareMarketMetric
from .repository import (
    StoreCareScheduleRepository,
    StoreCarePurchaseRepository,
    StoreCareMarketMetricRepository,
)


class StoreCareService:
    def __init__(
        self,
        schedule_repo: StoreCareScheduleRepository,
        purchase_repo: StoreCarePurchaseRepository,
        metrics_repo: StoreCareMarketMetricRepository | None = None,
    ):
        self.schedules = schedule_repo
        self.purchases = purchase_repo
        self.metrics = metrics_repo

    # ── 스케줄 CRUD ──

    async def list_schedules(self, tenant_id: str | None = None):
        """활성 스케줄 목록 조회."""
        return await self.schedules.list_active(tenant_id)

    async def create_schedule(self, data: dict) -> StoreCareSchedule:
        """스케줄 생성."""
        return await self.schedules.create_async(**data)

    async def update_schedule(self, schedule_id: str, data: dict):
        """스케줄 수정."""
        return await self.schedules.update_async(schedule_id, **data)

    async def delete_schedule(self, schedule_id: str):
        """스케줄 삭제."""
        return await self.schedules.delete_async(schedule_id)

    async def toggle_schedule(self, schedule_id: str) -> StoreCareSchedule | None:
        """스케줄 일시정지/재개 토글."""
        s = await self.schedules.get_async(schedule_id)
        if not s:
            return None
        new_status = "paused" if s.status != "paused" else "scheduled"
        await self.schedules.update_async(schedule_id, status=new_status)
        return await self.schedules.get_async(schedule_id)

    # ── 구매 이력 ──

    async def list_purchases(
        self,
        limit: int = 50,
        tenant_id: str | None = None,
        market_type: str | None = None,
    ):
        """최근 구매 이력 조회."""
        return await self.purchases.list_recent(limit, tenant_id, market_type)

    async def create_purchase(self, data: dict) -> StoreCarePurchase:
        """구매 이력 생성."""
        return await self.purchases.create_async(**data)

    async def today_stats(self, tenant_id: str | None = None):
        """오늘 가구매 통계."""
        return await self.purchases.today_stats(tenant_id)

    # ── 마켓 점수·품절률 ──

    async def list_market_metrics(self, tenant_id: str | None = None):
        """마켓별 최신 점수·품절률 스냅샷."""
        if not self.metrics:
            return []
        return await self.metrics.list_latest_per_market(tenant_id)

    async def list_recommendations(self, tenant_id: str | None = None):
        """가) 부족분 계산 — 마켓별 목표 대비 '사야 할 구매 갯수' 산정·표시."""
        from backend.domain.samba.proxy.sourcing_queue import STORE_METRICS_TARGETS

        if not self.metrics:
            return []
        rows = await self.metrics.list_latest_per_market(tenant_id)
        by_market = {r.market_type: r for r in rows}
        out: list[dict] = []
        for mt, target in STORE_METRICS_TARGETS.items():
            row = by_market.get(mt)
            if not row:
                out.append(
                    {
                        "market_type": mt,
                        "target": target,
                        "has_metric": False,
                        "current_value": None,
                        "denom": None,
                        "collected_at": None,
                        "recommendation": {
                            "qty": None,
                            "reason": "수집된 점수 없음 — 먼저 '지금 수집'",
                        },
                    }
                )
                continue
            cur = _current_value_for(target, row)
            denom = _extract_denom(row)
            denom_source = "portal"  # 기본: 포털 스크랩 N
            # 이행률 마켓(SSG/11번가)은 N 을 '삼바 주문수'(+버퍼)로 — 매일 삼바에서 검증 가능.
            # 삼바 카운트 실패/0 이면 포털 N 으로 폴백(기존 동작 보존).
            if target.get("metric") == "order_fulfillment" and mt in _SAMBA_N_CFG:
                samba_n = await _count_samba_order_n_safe(mt, tenant_id)
                if samba_n and samba_n > 0:
                    denom = _buffered_n(samba_n)
                    denom_source = f"samba+{_N_BUFFER_PCT}% (raw {samba_n})"
            out.append(
                {
                    "market_type": mt,
                    "target": target,
                    "has_metric": True,
                    "current_value": cur,
                    "denom": denom,
                    "denom_source": denom_source,
                    "collected_at": (
                        row.collected_at.isoformat() if row.collected_at else None
                    ),
                    "recommendation": recommend_purchase_qty(target, cur, denom),
                }
            )
        return out


# ── 확장앱 점수수집 결과 영속화 (공개 콜백에서 호출, 세션 자체 생성) ──


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _to_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


# ── 가) 부족분 계산형 — 목표 도달에 필요한 가구매 갯수 ──


def _current_value_for(target: dict, row) -> float | None:
    """target.metric 에 해당하는 현재값 추출."""
    if target.get("metric") == "soldout_rate":
        return row.soldout_rate
    return row.score  # order_fulfillment → 대표점수(주문이행)


def _extract_denom(row) -> int | None:
    """전체 주문수(분모 N) — 스크래퍼가 metrics JSON에 넣어주면 사용.

    포털 raw 확인 후 스크래퍼가 아래 키 중 하나로 N을 채운다. 없으면 None(계산 보류).
    """
    m = row.metrics or {}
    for key in (
        "전체주문",
        "총주문",
        "주문건수",
        "전체건수",
        "denom",
        "total_orders",
        "N",
    ):
        v = m.get(key)
        if isinstance(v, (int, float)):
            return int(v)
    return None


# ── 삼바 주문수 N (전체주문 분모) — 점수수집 '이행률' 마켓 한정 ──────────────
# 사용자 결정(2026-06-23): 주문이행률 분모 N 을 포털값 대신 '삼바 주문수'로 — 매일 삼바에서
# 바로 검증 가능(마켓마다 로그인해 전체주문 확인 비현실적). 마켓 판별은 주문목록 market_filter
# 와 동일(channel_id→SambaMarketAccount.market_type) + 플레이오토 경유 주문은
# sales_channel_alias 접두 매칭. 주문일(paid_at, 인덱스) 기준, 마켓 공식 기간.
# ⚠️ market_types/alias 문자열은 운영 데이터로 한 번 검증 권장(드롭다운 "11번가"·"신세계몰" 기반).
# GS(gsshop 품절률)는 매핑에서 제외 → 기존 포털 N 유지(별도 N 소스).
_N_BUFFER_PCT = (
    5  # 과소집계 보정 — 삼바 N < 마켓 N 갭 대비 과소구매 방지(이행률만). 추후 설정값화.
)
_SAMBA_N_CFG: dict[str, dict] = {
    "ssg": {
        "market_types": ["신세계몰", "이마트몰", "SSG"],
        "alias_prefixes": ["신세계몰", "이마트몰", "SSG"],
        "period_days": 30,  # SSG 매주 월요일 D-7~D-37 ≈ 롤링 30일
    },
    "11st": {
        "market_types": ["11번가"],
        "alias_prefixes": ["11번가"],
        "period_days": 30,  # 11번가 최근 1주/전 30일 → 30일 윈도우
    },
}


def _buffered_n(samba_n: int) -> int:
    """삼바 N 에 과소집계 보정 버퍼(+_N_BUFFER_PCT%) 적용(올림)."""
    return math.ceil(samba_n * (1 + _N_BUFFER_PCT / 100.0))


async def _count_samba_order_n(session, market_type: str, tenant_id) -> int | None:
    """점수수집 마켓의 삼바 주문수 N — 마켓 공식 기간 내 paid_at 기준.

    채널 직접 주문(channel_id→market_type) OR 플레이오토 경유(sales_channel_alias 접두) 매칭.
    매핑(_SAMBA_N_CFG) 없는 마켓(gsshop 품절률 등)은 None → 기존 포털 N 유지.
    """
    cfg = _SAMBA_N_CFG.get(market_type)
    if not cfg:
        return None
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, or_, select

    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.order.model import SambaOrder

    since = datetime.now(timezone.utc) - timedelta(days=int(cfg["period_days"]))

    # 1) market_type 매칭 마켓계정(channel_id) — 주문목록 market_filter 와 동일 로직
    acc_stmt = select(SambaMarketAccount.id).where(
        SambaMarketAccount.market_type.in_(cfg["market_types"])
    )
    if tenant_id is not None:
        acc_stmt = acc_stmt.where(
            or_(
                SambaMarketAccount.tenant_id == tenant_id,
                SambaMarketAccount.tenant_id == None,  # noqa: E711
            )
        )
    channel_ids = [r[0] for r in (await session.execute(acc_stmt)).all() if r[0]]

    # 2) 기간 내 주문 카운트 — (channel_id 직접) OR (alias 접두, 플레이오토 경유)
    market_conds = []
    if channel_ids:
        market_conds.append(SambaOrder.channel_id.in_(channel_ids))
    for p in cfg["alias_prefixes"]:
        market_conds.append(SambaOrder.sales_channel_alias.like(f"{p}%"))
    if not market_conds:
        return None

    cnt_stmt = (
        select(func.count())
        .select_from(SambaOrder)
        .where(SambaOrder.paid_at >= since, or_(*market_conds))
    )
    if tenant_id is not None:
        cnt_stmt = cnt_stmt.where(
            or_(
                SambaOrder.tenant_id == tenant_id,
                SambaOrder.tenant_id == None,  # noqa: E711
            )
        )
    n = (await session.execute(cnt_stmt)).scalar() or 0
    return int(n)


async def _count_samba_order_n_safe(market_type: str, tenant_id) -> int | None:
    """_count_samba_order_n 을 자체 읽기 세션으로 실행 + 실패 시 None(포털 N 폴백)."""
    try:
        from backend.db.orm import get_read_session

        async with get_read_session() as s:
            return await _count_samba_order_n(s, market_type, tenant_id)
    except Exception:  # noqa: BLE001
        return None


def recommend_purchase_qty(target: dict, current_value, denom) -> dict:
    """가) 부족분 계산. denom(전체 주문수 N) 필수.

    order_fulfillment(>= t): (F+k)/(N+k) >= t, F=r*N → k = ceil(N*(t-r)/(1-t))
    soldout_rate(< t):       S/(N+k) < t,     S=s*N → k = floor(S/t - N) + 1
    """
    if current_value is None:
        return {"qty": None, "reason": "현재값 없음"}
    metric = target.get("metric")
    t = float(target.get("value", 0)) / 100.0
    cur = float(current_value) / 100.0
    if denom is None or denom <= 0:
        return {
            "qty": None,
            "reason": "전체 주문수(분모 N) 필요 — 포털 수집/입력 시 자동계산",
        }
    N = float(denom)
    if metric == "order_fulfillment":
        if cur >= t:
            return {"qty": 0, "reason": "이미 목표 달성"}
        k = N * (t - cur) / (1 - t)
        return {
            "qty": max(0, math.ceil(k - 1e-9)),  # 1e-9: 부동소수점 과다올림 방지
            "reason": f"주문이행 {current_value}% → {target['value']}% (N={denom})",
        }
    if metric == "soldout_rate":
        if cur < t:
            return {"qty": 0, "reason": "이미 목표 이하"}
        S = cur * N
        k = math.floor(S / t - N + 1e-9) + 1  # 1e-9: 부동소수점 과소내림 방지
        return {
            "qty": max(0, k),
            "reason": f"품절률 {current_value}% → <{target['value']}% (N={denom})",
        }
    return {"qty": None, "reason": f"unknown metric {metric}"}


async def apply_store_metrics_result(request_id: str, data: dict) -> dict:
    """확장앱 점수수집 결과 → StoreCareMarketMetric 적재.

    잡 payload(samba_sourcing_job)에서 tenant_id/market_type/account 정보를 복원한다.
    """
    from backend.db.orm import get_write_session
    from backend.domain.samba.sourcing_job.model import SambaSourcingJob

    async with get_write_session() as session:
        job = await session.get(SambaSourcingJob, request_id)
        payload = (job.payload if job else None) or {}
        market_type = (
            payload.get("marketType") or data.get("marketType") or "unknown"
        ).lower()
        metric = StoreCareMarketMetric(
            tenant_id=payload.get("tenantId") or None,
            market_type=market_type,
            account_id=payload.get("accountId") or None,
            account_label=payload.get("accountLabel") or "",
            soldout_rate=_to_float(data.get("soldoutRate")),
            soldout_rate_prev=_to_float(data.get("soldoutRatePrev")),
            score=_to_float(data.get("score")),
            grade=(data.get("grade") or None),
            penalty=_to_int(data.get("penalty")),
            metrics=data.get("metrics") or None,
            raw=data.get("raw") or None,
            period_label=(data.get("periodLabel") or None),
            status="ok" if data.get("success") else "failed",
            error=(data.get("error") or None),
            source_url=payload.get("url") or None,
        )
        session.add(metric)
        await session.commit()
        return {"market_type": market_type, "metric_id": metric.id}
