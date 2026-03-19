"""SambaWave 워룸(모니터링) API 라우터."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.collector.refresher import get_refresh_logs, get_site_intervals_info
from backend.domain.samba.warroom.service import SambaMonitorService
from backend.domain.samba.warroom.repository import SambaMonitorEventRepository

router = APIRouter(prefix="/monitor", tags=["samba-monitor"])


@router.get("/dashboard")
async def get_dashboard(
  session: AsyncSession = Depends(get_read_session_dependency),
):
  """대시보드 전체 통계 (30초 폴링 대상)."""
  svc = SambaMonitorService(session)
  return await svc.get_dashboard_stats()


@router.get("/events")
async def list_events(
  event_type: Optional[str] = Query(None),
  severity: Optional[str] = Query(None),
  limit: int = Query(50, ge=1, le=200),
  session: AsyncSession = Depends(get_read_session_dependency),
):
  """이벤트 목록 — 필터 가능."""
  repo = SambaMonitorEventRepository(session)

  if severity:
    events = await repo.list_by_severity(severity, limit)
  elif event_type:
    events = await repo.list_by_type(event_type, limit)
  else:
    events = await repo.list_recent(limit)

  return [
    {
      "id": e.id,
      "event_type": e.event_type,
      "severity": e.severity,
      "source_site": e.source_site,
      "market_type": e.market_type,
      "product_id": e.product_id,
      "product_name": e.product_name,
      "summary": e.summary,
      "detail": e.detail,
      "created_at": e.created_at.isoformat(),
    }
    for e in events
  ]


@router.get("/events/recent")
async def list_recent_events(
  limit: int = Query(50, ge=1, le=100),
  session: AsyncSession = Depends(get_read_session_dependency),
):
  """최근 이벤트 50건."""
  repo = SambaMonitorEventRepository(session)
  events = await repo.list_recent(limit)
  return [
    {
      "id": e.id,
      "event_type": e.event_type,
      "severity": e.severity,
      "source_site": e.source_site,
      "market_type": e.market_type,
      "product_id": e.product_id,
      "product_name": e.product_name,
      "summary": e.summary,
      "detail": e.detail,
      "created_at": e.created_at.isoformat(),
    }
    for e in events
  ]


@router.get("/price-changes")
async def list_price_changes(
  session: AsyncSession = Depends(get_read_session_dependency),
):
  """최근 24시간 가격 변동 이벤트."""
  repo = SambaMonitorEventRepository(session)
  events = await repo.list_by_type("price_changed", limit=100)

  now = datetime.now(timezone.utc)
  since_24h = now - timedelta(hours=24)
  recent = [e for e in events if e.created_at >= since_24h]

  return [
    {
      "id": e.id,
      "product_id": e.product_id,
      "product_name": e.product_name,
      "source_site": e.source_site,
      "detail": e.detail,
      "created_at": e.created_at.isoformat(),
    }
    for e in recent
  ]


@router.get("/site-health")
async def get_site_health(
  session: AsyncSession = Depends(get_read_session_dependency),
):
  """소싱처/마켓 헬스 상태."""
  svc = SambaMonitorService(session)
  site_health = await svc._get_site_health()
  market_health = await svc._get_market_health()
  return {
    "sources": site_health,
    "markets": market_health,
  }


@router.get("/refresh-logs")
async def get_refresh_log_entries(
  since_idx: int = Query(0, ge=0),
):
  """오토튠 실시간 로그 (인메모리 링 버퍼). since_idx 이후 증분 반환."""
  logs, current_idx = get_refresh_logs(since_idx)
  intervals_info = get_site_intervals_info()
  return {
    "logs": logs,
    "current_idx": current_idx,
    "intervals": intervals_info,
  }


@router.delete("/events/cleanup")
async def cleanup_old_events(
  days: int = Query(30, ge=1, le=365),
  session: AsyncSession = Depends(get_write_session_dependency),
):
  """오래된 이벤트 정리."""
  before = datetime.now(timezone.utc) - timedelta(days=days)
  repo = SambaMonitorEventRepository(session)
  deleted = await repo.cleanup_old(before)
  await session.commit()
  return {"deleted": deleted}
