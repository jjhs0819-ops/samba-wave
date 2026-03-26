"""SambaWave 모니터링 서비스 — 이벤트 발행 + 대시보드 통계."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.warroom.model import SambaMonitorEvent
from backend.domain.samba.warroom.repository import SambaMonitorEventRepository
from backend.utils.logger import logger


_RETENTION_DAYS = 30  # 이벤트 보존 기간
_emit_counter = 0  # 100회마다 정리 실행


class SambaMonitorService:
  def __init__(self, session: AsyncSession):
    self.session = session
    self.repo = SambaMonitorEventRepository(session)

  async def emit(
    self,
    event_type: str,
    severity: str = "info",
    summary: str = "",
    source_site: Optional[str] = None,
    market_type: Optional[str] = None,
    product_id: Optional[str] = None,
    product_name: Optional[str] = None,
    detail: Optional[Any] = None,
  ) -> None:
    """이벤트 기록 — 메인 로직을 방해하지 않도록 try/except 감싸기."""
    global _emit_counter
    try:
      event = SambaMonitorEvent(
        event_type=event_type,
        severity=severity,
        summary=summary,
        source_site=source_site,
        market_type=market_type,
        product_id=product_id,
        product_name=product_name,
        detail=detail,
      )
      self.session.add(event)
      await self.session.flush()

      # 100회마다 30일 이전 이벤트 자동 정리
      _emit_counter += 1
      if _emit_counter >= 100:
        _emit_counter = 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
        deleted = await self.repo.cleanup_old(cutoff)
        if deleted:
          logger.info(f"[monitor] {_RETENTION_DAYS}일 이전 이벤트 {deleted}건 정리")
    except Exception as e:
      logger.warning(f"[monitor] 이벤트 기록 실패: {e}")

  async def get_dashboard_stats(self) -> Dict[str, Any]:
    """대시보드 전체 통계 — 단일 호출로 반환."""
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    since_1h = now - timedelta(hours=1)

    # 상품 통계
    product_stats = await self._get_product_stats()

    # 갱신 통계
    refresh_stats = await self._get_refresh_stats(since_1h, since_24h)

    # 가격 변동 통계
    price_change_stats = await self._get_price_change_stats(since_24h)

    # 소싱처/마켓 헬스
    site_health = await self._get_site_health()
    market_health = await self._get_market_health()

    # 이벤트 요약
    event_summary = await self._get_event_summary(since_24h)

    # 시간대별 변동 건수 (24시간)
    hourly_changes = await self._get_hourly_changes(since_24h)

    return {
      "product_stats": product_stats,
      "refresh_stats": refresh_stats,
      "price_change_stats": price_change_stats,
      "site_health": site_health,
      "market_health": market_health,
      "event_summary": event_summary,
      "hourly_changes": hourly_changes,
    }

  async def _get_product_stats(self) -> Dict[str, Any]:
    """상품 통계: 전체, 소싱처별, 우선순위별, 상태별."""
    from backend.domain.samba.collector.model import SambaCollectedProduct

    # 전체 카운트
    total_stmt = select(func.count(SambaCollectedProduct.id))
    total_result = await self.session.execute(total_stmt)
    total = total_result.scalar() or 0

    # 소싱처별 카운트
    by_source_stmt = (
      select(
        SambaCollectedProduct.source_site,
        func.count(SambaCollectedProduct.id),
      )
      .group_by(SambaCollectedProduct.source_site)
    )
    by_source_result = await self.session.execute(by_source_stmt)
    by_source = {row[0]: row[1] for row in by_source_result.all()}

    # 우선순위별
    by_priority_stmt = (
      select(
        SambaCollectedProduct.monitor_priority,
        func.count(SambaCollectedProduct.id),
      )
      .group_by(SambaCollectedProduct.monitor_priority)
    )
    by_priority_result = await self.session.execute(by_priority_stmt)
    by_priority = {row[0]: row[1] for row in by_priority_result.all()}

    # 상태별
    by_status_stmt = (
      select(
        SambaCollectedProduct.sale_status,
        func.count(SambaCollectedProduct.id),
      )
      .group_by(SambaCollectedProduct.sale_status)
    )
    by_status_result = await self.session.execute(by_status_stmt)
    by_sale_status = {row[0]: row[1] for row in by_status_result.all()}

    return {
      "total": total,
      "by_source": by_source,
      "by_priority": by_priority,
      "by_sale_status": by_sale_status,
    }

  async def _get_refresh_stats(
    self, since_1h: datetime, since_24h: datetime,
  ) -> Dict[str, Any]:
    """갱신 통계."""
    from backend.domain.samba.collector.model import SambaCollectedProduct

    # 마지막 갱신 시각
    last_stmt = (
      select(SambaCollectedProduct.last_refreshed_at)
      .where(SambaCollectedProduct.last_refreshed_at.isnot(None))
      .order_by(SambaCollectedProduct.last_refreshed_at.desc())
      .limit(1)
    )
    last_result = await self.session.execute(last_stmt)
    last_refreshed = last_result.scalar()

    # 1시간 내 갱신
    r1h_stmt = (
      select(func.count(SambaCollectedProduct.id))
      .where(SambaCollectedProduct.last_refreshed_at >= since_1h)
    )
    r1h_result = await self.session.execute(r1h_stmt)
    refreshed_1h = r1h_result.scalar() or 0

    # 24시간 내 갱신
    r24h_stmt = (
      select(func.count(SambaCollectedProduct.id))
      .where(SambaCollectedProduct.last_refreshed_at >= since_24h)
    )
    r24h_result = await self.session.execute(r24h_stmt)
    refreshed_24h = r24h_result.scalar() or 0

    # 에러 상품 (refresh_error_count > 0)
    err_stmt = (
      select(func.count(SambaCollectedProduct.id))
      .where(SambaCollectedProduct.refresh_error_count > 0)
    )
    err_result = await self.session.execute(err_stmt)
    error_products = err_result.scalar() or 0

    return {
      "last_refreshed_at": last_refreshed.isoformat() if last_refreshed else None,
      "refreshed_1h": refreshed_1h,
      "refreshed_24h": refreshed_24h,
      "error_products": error_products,
    }

  async def _get_price_change_stats(
    self, since_24h: datetime,
  ) -> Dict[str, Any]:
    """24시간 가격 변동 통계."""
    # 이벤트 기반 가격 변동 조회
    events = await self.repo.list_by_type("price_changed", limit=100)
    recent_events = [
      e for e in events
      if e.created_at >= since_24h
    ]

    changes_24h = len(recent_events)

    # 평균 변동률 + TOP 변동
    top_changes: List[Dict[str, Any]] = []
    total_pct = 0.0
    for e in recent_events[:10]:
      d = e.detail or {}
      pct = d.get("diff_pct", 0)
      total_pct += pct
      top_changes.append({
        "product_id": e.product_id,
        "name": e.product_name or "",
        "old": d.get("old_price", 0),
        "new": d.get("new_price", 0),
        "pct": round(pct, 1),
        "at": e.created_at.isoformat(),
      })

    avg_change_pct = round(total_pct / changes_24h, 1) if changes_24h > 0 else 0

    return {
      "changes_24h": changes_24h,
      "avg_change_pct": avg_change_pct,
      "top_changes": top_changes,
    }

  async def _get_site_health(self) -> Dict[str, Any]:
    """소싱처 헬스 상태."""
    from backend.domain.samba.collector.refresher import (
      _site_intervals,
      _site_consecutive_errors,
    )
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository

    result: Dict[str, Any] = {}
    repo = SambaSettingsRepository(self.session)

    # probe 결과 조회
    from backend.domain.samba.probe.health_checker import PROBE_TARGETS
    for site in ["MUSINSA", "KREAM"]:
      probe_data = None
      row = await repo.find_by_async(key=f"probe_{site}")
      if row and row.value:
        probe_data = row.value

      result[site] = {
        "interval": _site_intervals.get(site, 1.0),
        "errors": _site_consecutive_errors.get(site, 0),
        "probe_ok": probe_data.get("ok") if probe_data else None,
        "latency_ms": probe_data.get("latency_ms", 0) if probe_data else None,
        "checked_at": probe_data.get("checked_at") if probe_data else None,
      }

    return result

  async def _get_market_health(self) -> Dict[str, Any]:
    """마켓 헬스 상태."""
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository
    from backend.domain.samba.probe.health_checker import MARKET_PROBES

    result: Dict[str, Any] = {}
    repo = SambaSettingsRepository(self.session)

    for mt in MARKET_PROBES:
      row = await repo.find_by_async(key=f"probe_market_{mt}")
      if row and row.value:
        d = row.value
        result[mt] = {
          "probe_ok": d.get("ok"),
          "latency_ms": d.get("latency_ms", 0),
          "error": d.get("error"),
          "checked_at": d.get("checked_at"),
        }

    return result

  async def _get_event_summary(
    self, since_24h: datetime,
  ) -> Dict[str, Any]:
    """이벤트 요약: 24시간 타입별 카운트 + 최근 위험/경고."""
    counts = await self.repo.count_by_type_since(since_24h)
    recent_critical = await self.repo.list_by_severity("critical", limit=5)
    recent_warnings = await self.repo.list_by_severity("warning", limit=10)

    def _serialize(e: SambaMonitorEvent) -> Dict[str, Any]:
      return {
        "id": e.id,
        "event_type": e.event_type,
        "severity": e.severity,
        "source_site": e.source_site,
        "product_name": e.product_name,
        "summary": e.summary,
        "created_at": e.created_at.isoformat(),
      }

    return {
      "counts_24h": counts,
      "recent_critical": [_serialize(e) for e in recent_critical],
      "recent_warnings": [_serialize(e) for e in recent_warnings],
    }

  async def _get_hourly_changes(
    self, since_24h: datetime,
  ) -> List[int]:
    """24시간 시간대별 가격변동 건수 (0시~23시)."""
    hourly_data = await self.repo.count_hourly_since("price_changed", since_24h)
    hour_map = {item["hour"]: item["count"] for item in hourly_data}
    return [hour_map.get(h, 0) for h in range(24)]
