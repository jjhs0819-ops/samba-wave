"""마켓(판매처)별 전송 잡 러닝/펜딩 현황 조회 (진단용)."""

import asyncio
import sys

sys.path.insert(0, "/app/backend")


async def main():
    from sqlalchemy import func, select, text

    from backend.db.orm import get_read_session
    from backend.domain.samba.job.model import JobStatus, SambaJob

    mkt = SambaJob.payload["market_type"].as_string()

    async with get_read_session() as s:
        stmt = (
            select(mkt, SambaJob.job_type, SambaJob.status, func.count())
            .where(
                SambaJob.job_type.in_(["transmit", "autotune_transmit"]),
                SambaJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
            )
            .group_by(text("1"), text("2"), text("3"))
        )
        rows = (await s.execute(stmt)).all()

    # {market: {"running": n, "pending": n}}
    agg: dict[str, dict[str, int]] = {}
    for market_type, job_type, status, cnt in rows:
        m = str(market_type or "(빈값)")
        d = agg.setdefault(m, {"running": 0, "pending": 0})
        if status == JobStatus.RUNNING:
            d["running"] += int(cnt or 0)
        elif status == JobStatus.PENDING:
            d["pending"] += int(cnt or 0)

    print("=== 마켓(판매처)별 전송 잡 현황 (transmit + autotune_transmit) ===")
    print(f"{'마켓':<16}{'러닝':>8}{'펜딩':>10}")
    tot_r = tot_p = 0
    for m in sorted(agg, key=lambda k: -(agg[k]["running"] + agg[k]["pending"])):
        r = agg[m]["running"]
        p = agg[m]["pending"]
        tot_r += r
        tot_p += p
        print(f"{m:<16}{r:>8,}{p:>10,}")
    print("-" * 34)
    print(f"{'합계':<16}{tot_r:>8,}{tot_p:>10,}")


asyncio.run(main())
