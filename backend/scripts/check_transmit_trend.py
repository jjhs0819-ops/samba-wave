"""전송 잡 상태별 + 최근 처리량 추이 조회 (펜딩 해소 진위 검증)."""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/backend")

UTC = timezone.utc


async def main():
    from sqlalchemy import func, select

    from backend.db.orm import get_read_session
    from backend.domain.samba.job.model import SambaJob

    types = ["transmit", "autotune_transmit"]
    now = datetime.now(UTC)
    h1 = now - timedelta(hours=1)
    m30 = now - timedelta(minutes=30)

    async with get_read_session() as s:
        # 1) 현재 상태별 전체 카운트
        by_status = (
            await s.execute(
                select(SambaJob.status, func.count())
                .where(SambaJob.job_type.in_(types))
                .group_by(SambaJob.status)
            )
        ).all()

        # 2) 최근 1시간 생성된 잡 (= 오토튠이 계속 발행 중인가)
        created_1h = (
            await s.execute(
                select(func.count()).where(
                    SambaJob.job_type.in_(types), SambaJob.created_at >= h1
                )
            )
        ).scalar()

        # 3) 최근 30분 완료된 잡 (= B가 계속 처리 중인가)
        done_30m = (
            await s.execute(
                select(func.count()).where(
                    SambaJob.job_type.in_(types),
                    SambaJob.completed_at.is_not(None),
                    SambaJob.completed_at >= m30,
                )
            )
        ).scalar()

        # 4) 가장 오래된 펜딩 (적체 나이)
        oldest_pending = (
            await s.execute(
                select(func.min(SambaJob.created_at)).where(
                    SambaJob.job_type.in_(types), SambaJob.status == "pending"
                )
            )
        ).scalar()

    print("=== 전송 잡 상태별 현재 카운트 ===")
    for st, cnt in by_status:
        print(f"  {str(st):<14}{int(cnt or 0):>8,}")
    print()
    print(f"최근 1시간 신규 발행: {int(created_1h or 0):,}건  (오토튠 발행 활성 여부)")
    print(f"최근 30분 완료    : {int(done_30m or 0):,}건  (B 처리 활성 여부)")
    if oldest_pending:
        age = (now - oldest_pending.replace(tzinfo=UTC)).total_seconds() / 60
        print(f"가장 오래된 펜딩  : {age:,.1f}분 전 생성")
    else:
        print("가장 오래된 펜딩  : 없음")


asyncio.run(main())
