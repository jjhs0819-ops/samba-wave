"""GSSHOP 주문 product_id → samba_collected_product.site_product_id 매칭 확인."""

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text  # noqa: E402

from backend.db.orm import get_read_session  # noqa: E402


async def main() -> None:
    async with get_read_session() as s:
        # alias 없는 GS샵 미등록 주문의 product_id 샘플 100개
        pid_rows = (
            await s.execute(
                text(
                    "SELECT DISTINCT o.product_id FROM samba_order o "
                    "WHERE o.source = 'playauto' "
                    "AND o.collected_product_id IS NULL "
                    "AND o.product_id IS NOT NULL AND o.product_id != '' "
                    "AND (o.sales_channel_alias IS NULL OR o.sales_channel_alias = '') "
                    "LIMIT 100"
                )
            )
        ).fetchall()
        pids = [str(r[0]).strip() for r in pid_rows]
        print(f"product_id 샘플: {len(pids)}개")
        print(f"  예시: {pids[:5]}")

        # samba_collected_product.site_product_id 로 매칭 시도
        hit_rows = (
            await s.execute(
                text(
                    "SELECT cp.id, cp.site_product_id, cp.source_site, cp.name "
                    "FROM samba_collected_product cp "
                    "WHERE cp.source_site = 'gsshop' "
                    "AND cp.site_product_id = ANY(:pids) "
                    "LIMIT 20"
                ),
                {"pids": pids},
            )
        ).fetchall()
        print(f"\nsite_product_id 히트: {len(hit_rows)}건")
        for r in hit_rows:
            print(f"  {r[1]} → {str(r[3] or '')[:50]}")

        # 전체 통계: 미등록 GS샵 주문 중 매칭 가능 비율
        all_pid_rows = (
            await s.execute(
                text(
                    "SELECT DISTINCT o.product_id FROM samba_order o "
                    "WHERE o.source = 'playauto' "
                    "AND o.collected_product_id IS NULL "
                    "AND o.product_id IS NOT NULL AND o.product_id != '' "
                    "AND (o.sales_channel_alias IS NULL OR o.sales_channel_alias = '') "
                )
            )
        ).fetchall()
        all_pids = [str(r[0]).strip() for r in all_pid_rows]

        matchable = (
            await s.execute(
                text(
                    "SELECT COUNT(DISTINCT site_product_id) "
                    "FROM samba_collected_product "
                    "WHERE source_site = 'gsshop' AND site_product_id = ANY(:pids)"
                ),
                {"pids": all_pids},
            )
        ).scalar()
        print(
            f"\n전체 미등록 GS샵 unique product_id: {len(all_pids):,}개"
            f"\nsite_product_id 매칭 가능: {matchable:,}개"
        )

        # GS이숍(고경/마놀/캐논) alias 있는 주문도 확인
        gs_alias_pids = (
            await s.execute(
                text(
                    "SELECT DISTINCT o.product_id FROM samba_order o "
                    "WHERE o.source = 'playauto' "
                    "AND o.collected_product_id IS NULL "
                    "AND o.product_id IS NOT NULL "
                    "AND o.sales_channel_alias LIKE 'GS%' "
                )
            )
        ).fetchall()
        gs_pids = [str(r[0]).strip() for r in gs_alias_pids]
        if gs_pids:
            gs_match = (
                await s.execute(
                    text(
                        "SELECT COUNT(DISTINCT site_product_id) "
                        "FROM samba_collected_product "
                        "WHERE source_site = 'gsshop' AND site_product_id = ANY(:pids)"
                    ),
                    {"pids": gs_pids},
                )
            ).scalar()
            print(
                f"\nGS이숍(alias) 미등록 unique product_id: {len(gs_pids):,}개"
                f"\nsite_product_id 매칭 가능: {gs_match:,}개"
            )


asyncio.run(main())
