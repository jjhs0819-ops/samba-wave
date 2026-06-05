"""유령 배너 과대집계 검증 — naive 48h 합 vs 계정별 최신1건 합."""

import asyncio
import json

from sqlalchemy import text

from backend.db.orm import get_write_session


def _count(detail):
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except Exception:
            detail = {}
    detail = detail or {}
    for k in ("total_missing", "ghosts", "total"):
        v = detail.get(k)
        if isinstance(v, (int, float)):
            return int(v), detail.get("account_label") or detail.get("account_id")
    return 0, None


async def main() -> None:
    async with get_write_session() as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT event_type, market_type, detail, created_at "
                        "FROM samba_monitor_event "
                        "WHERE event_type IN ('lotteon_ghost_detected',"
                        "'elevenst_missing_prdno_detected','smartstore_ghost_detected') "
                        "AND created_at >= NOW() - interval '48 hours' "
                        "ORDER BY created_at DESC"
                    )
                )
            )
            .mappings()
            .all()
        )

    naive: dict[str, int] = {}
    naive_n: dict[str, int] = {}
    latest: dict[str, dict] = {}  # market -> {acct -> count(최신)}
    for r in rows:
        m = r["market_type"] or "unknown"
        n, acct = _count(r["detail"])
        naive[m] = naive.get(m, 0) + n
        naive_n[m] = naive_n.get(m, 0) + 1
        latest.setdefault(m, {})
        if acct not in latest[m]:  # DESC 정렬이라 첫 등장 = 최신
            latest[m][acct] = n

    print("=== 48h 이벤트 수 / naive합(현재 배너) / 계정별최신합(정상) ===")
    for m in sorted(naive):
        correct = sum(latest[m].values())
        print(
            f"{m:>12} | events={naive_n[m]:>4} | naive합={naive[m]:>6} | "
            f"정상합={correct:>5} | 배율={naive[m] / max(correct, 1):.1f}x | "
            f"계정수={len(latest[m])}"
        )


if __name__ == "__main__":
    asyncio.run(main())
