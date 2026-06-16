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
            out.append(
                {
                    "market_type": mt,
                    "target": target,
                    "has_metric": True,
                    "current_value": cur,
                    "denom": denom,
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
