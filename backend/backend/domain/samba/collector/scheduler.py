"""모니터링 스케줄러 — 우선순위 기반 갱신 대상 선별.

외부 cron이 /collector/scheduler/tick을 10분마다 호출하면
이 모듈이 우선순위별 대상 상품을 반환한다.
상품 수가 적으면 동적으로 인터벌을 축소하여 더 자주 갱신한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List

from sqlalchemy import and_, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.collector.model import SambaCollectedProduct

# 기본 우선순위별 갱신 주기
DEFAULT_INTERVALS: Dict[str, timedelta] = {
    "hot": timedelta(minutes=10),
    "warm": timedelta(hours=1),
    "cold": timedelta(hours=6),
}

# 에러 횟수 초과 시 제외
MAX_ERROR_COUNT = 3

# 1회 배치 최대 건수
BATCH_SIZE = 500


def _compute_intervals(product_count: int) -> Dict[str, timedelta]:
    """상품 수에 따라 동적 인터벌 계산.

    - ≤200: 전부 10분 간격 (COLD/WARM 구분 없이)
    - ≤1000: HOT 5분, 나머지 15분
    - >1000: 기본값 사용
    """
    if product_count <= 200:
        return {
            "hot": timedelta(minutes=10),
            "warm": timedelta(minutes=10),
            "cold": timedelta(minutes=10),
        }
    if product_count <= 1000:
        return {
            "hot": timedelta(minutes=5),
            "warm": timedelta(minutes=15),
            "cold": timedelta(minutes=15),
        }
    return dict(DEFAULT_INTERVALS)


async def get_refresh_candidates(
    session: AsyncSession,
    now: datetime | None = None,
) -> List[str]:
    """현재 시각 기준 갱신 대상 상품 ID 반환.

    상품 수에 따라 인터벌을 동적으로 조절한다:
    - ≤200건: 전부 10분 간격
    - ≤1000건: HOT 5분, 나머지 15분
    - >1000건: HOT 10분, WARM 1시간, COLD 6시간
    - refresh_error_count > 3이면 제외
    - 배치 크기 제한: 1회 최대 500건
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # 전체 상품 수 조회하여 동적 인터벌 결정
    count_result = await session.execute(
        select(func.count()).select_from(SambaCollectedProduct)
    )
    product_count = count_result.scalar() or 0
    intervals = _compute_intervals(product_count)

    conditions = []
    for priority, interval in intervals.items():
        cutoff = now - interval
        conditions.append(
            and_(
                SambaCollectedProduct.monitor_priority == priority,
                or_(
                    SambaCollectedProduct.last_refreshed_at.is_(None),
                    SambaCollectedProduct.last_refreshed_at < cutoff,
                ),
            )
        )

    stmt = (
        select(SambaCollectedProduct.id)
        .where(
            and_(
                SambaCollectedProduct.refresh_error_count <= MAX_ERROR_COUNT,
                or_(*conditions),
            )
        )
        .order_by(
            # HOT 우선, 그 다음 WARM, COLD
            SambaCollectedProduct.last_refreshed_at.asc().nullsfirst()
        )
        .limit(BATCH_SIZE)
    )

    result = await session.execute(stmt)
    return list(result.scalars().all())
