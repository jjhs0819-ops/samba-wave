"""channel_alias 없는 플레이오토 미등록 주문 5,242건 원인 파악."""

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text  # noqa: E402

from backend.db.orm import get_read_session  # noqa: E402


async def main() -> None:
    async with get_read_session() as s:
        # alias 없는 미등록 샘플
        rows = (
            await s.execute(
                text(
                    "SELECT o.id, o.product_id, o.channel_id, o.product_name, "
                    "       o.source_url, o.source_site "
                    "FROM samba_order o "
                    "WHERE o.source = 'playauto' "
                    "AND o.collected_product_id IS NULL "
                    "AND (o.sales_channel_alias IS NULL OR o.sales_channel_alias = '') "
                    "ORDER BY o.created_at DESC "
                    "LIMIT 10"
                )
            )
        ).fetchall()

        print(f"alias 없는 미등록 샘플 {len(rows)}건:")
        for r in rows:
            print(
                f"  product_id={str(r[1] or ''):<20s} "
                f"channel_id={str(r[2] or ''):<36s} "
                f"source_url={str(r[4] or '')[:30]} "
                f"source_site={r[5]!r} "
                f"name={str(r[3] or '')[:40]}"
            )

        # source_url 채워진 비율 (이미 등록으로 처리된 것 있는지)
        url_filled = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM samba_order "
                    "WHERE source = 'playauto' "
                    "AND collected_product_id IS NULL "
                    "AND (sales_channel_alias IS NULL OR sales_channel_alias = '') "
                    "AND source_url IS NOT NULL AND source_url != ''"
                )
            )
        ).scalar()
        print(f"\nalias 없는 미등록 중 source_url 있는 건수: {url_filled:,}")

        # 가장 오래된 날짜 확인
        oldest = (
            await s.execute(
                text(
                    "SELECT MIN(created_at) FROM samba_order "
                    "WHERE source = 'playauto' "
                    "AND collected_product_id IS NULL "
                    "AND (sales_channel_alias IS NULL OR sales_channel_alias = '')"
                )
            )
        ).scalar()
        print(f"가장 오래된 날짜: {oldest}")

        # market_product_nos 히트 확인 — 이 주문들의 product_id가 CP에 있는지
        pid_rows = (
            await s.execute(
                text(
                    "SELECT DISTINCT o.product_id FROM samba_order o "
                    "WHERE o.source = 'playauto' "
                    "AND o.collected_product_id IS NULL "
                    "AND (o.sales_channel_alias IS NULL OR o.sales_channel_alias = '') "
                    "AND o.product_id IS NOT NULL AND o.product_id != '' "
                    "LIMIT 100"
                )
            )
        ).fetchall()
        pids = [str(r[0]) for r in pid_rows]
        if pids:
            ph = ", ".join(f"'{p}'" for p in pids[:50])
            # market_product_nos 값에 이 product_id 가 있으면 매칭 가능
            hit = (
                await s.execute(
                    text(
                        f"SELECT COUNT(*) FROM samba_collected_product "
                        f"WHERE market_product_nos::text ~ ANY(ARRAY[{','.join(repr(p) for p in pids[:20])}])"
                    )
                )
            ).scalar()
            print(f"product_id→market_product_nos 히트: {hit}건 / {len(pids)}개 조회")


asyncio.run(main())
