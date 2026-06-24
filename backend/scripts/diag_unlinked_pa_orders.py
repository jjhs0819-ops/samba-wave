"""미등록 PlayAuto 주문 상세 진단."""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text

from backend.db.orm import get_read_session

PA_ACCOUNT_ID = "ma_01KP0919YA061YX5PHH25KWJAK"


async def main() -> None:
    async with get_read_session() as s:
        # 1) 미등록 주문 날짜 분포
        age_dist = (
            await s.execute(
                text(
                    "SELECT "
                    "  CASE WHEN created_at >= NOW() - INTERVAL '30 days' THEN '최근30일' "
                    "       WHEN created_at >= NOW() - INTERVAL '90 days' THEN '30~90일' "
                    "       WHEN created_at >= NOW() - INTERVAL '180 days' THEN '90~180일' "
                    "       ELSE '180일이상' END AS age, "
                    "  COUNT(*) AS cnt "
                    "FROM samba_order "
                    "WHERE source = 'playauto' AND collected_product_id IS NULL "
                    "GROUP BY 1 ORDER BY 1"
                )
            )
        ).fetchall()
        print("미등록 PlayAuto 주문 날짜 분포:")
        for r in age_dist:
            print(f"  {r[0]}: {r[1]:,}건")

        # 2) 미등록 주문 order_number 샘플 (형식 확인)
        samples = (
            await s.execute(
                text(
                    "SELECT order_number, channel_name, channel_id, created_at "
                    "FROM samba_order "
                    "WHERE source = 'playauto' AND collected_product_id IS NULL "
                    "AND created_at >= NOW() - INTERVAL '30 days' "
                    "LIMIT 5"
                )
            )
        ).fetchall()
        print(f"\n최근 30일 미등록 주문 샘플:")
        for r in samples:
            print(f"  order_no={r[0]!r} channel={r[1]} ch_id={str(r[2])[:20]} dt={r[3]}")

        # 3) 최근 30일 미등록 주문 channel별 분포
        ch_dist = (
            await s.execute(
                text(
                    "SELECT channel_name, COUNT(*) AS cnt "
                    "FROM samba_order "
                    "WHERE source = 'playauto' AND collected_product_id IS NULL "
                    "AND created_at >= NOW() - INTERVAL '30 days' "
                    "GROUP BY channel_name ORDER BY cnt DESC"
                )
            )
        ).fetchall()
        print(f"\n최근 30일 미등록 주문 채널 분포:")
        for r in ch_dist:
            print(f"  {r[0]}: {r[1]:,}건")

        # 4) 전체 미등록 주문 채널별 분포
        ch_all = (
            await s.execute(
                text(
                    "SELECT channel_name, COUNT(*) AS cnt "
                    "FROM samba_order "
                    "WHERE source = 'playauto' AND collected_product_id IS NULL "
                    "GROUP BY channel_name ORDER BY cnt DESC LIMIT 10"
                )
            )
        ).fetchall()
        print(f"\n전체 미등록 주문 채널 분포:")
        for r in ch_all:
            print(f"  {r[0]}: {r[1]:,}건")

        # 5) product_id 샘플 (ProdCode)
        pid_samples = (
            await s.execute(
                text(
                    "SELECT product_id, channel_name "
                    "FROM samba_order "
                    "WHERE source = 'playauto' AND collected_product_id IS NULL "
                    "AND product_id IS NOT NULL AND product_id != '' "
                    "AND created_at >= NOW() - INTERVAL '7 days' "
                    "LIMIT 5"
                )
            )
        ).fetchall()
        print(f"\n최근 7일 미등록 주문 product_id:")
        for r in pid_samples:
            print(f"  product_id={r[0]!r} channel={r[1]}")

        # 6) MasterCode가 있는 주문 (product_id가 AM으로 시작하는 건 없는지)
        am_pid = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM samba_order "
                    "WHERE source = 'playauto' AND collected_product_id IS NULL "
                    "AND product_id LIKE 'AM%'"
                )
            )
        ).scalar()
        print(f"\nproduct_id가 AM으로 시작하는 미등록 주문: {am_pid:,}건")


asyncio.run(main())
