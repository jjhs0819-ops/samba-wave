"""PlayAuto 미등록 주문 → site_product_id 기반 CP 백필.

GS이숍 주문 product_id(마켓상품번호) = CP.site_product_id(소싱처 상품ID) 직접 매칭.
로직:
  1. 미등록 주문 product_id 목록
  2. samba_collected_product.site_product_id == product_id 매칭
  3. collected_product_id UPDATE
"""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text

from backend.db.orm import get_read_session, get_write_session


async def main() -> None:
    async with get_read_session() as s:
        # 1) 미등록 주문 목록 (product_id 있는 것만)
        unlinked = (
            await s.execute(
                text(
                    "SELECT id, product_id, channel_name FROM samba_order "
                    "WHERE source = 'playauto' AND collected_product_id IS NULL "
                    "AND product_id IS NOT NULL AND product_id != ''"
                )
            )
        ).fetchall()
        print(f"미등록 PlayAuto 주문 (product_id 있음): {len(unlinked):,}건")

        # 2) site_product_id 기반 매칭 (단일 쿼리)
        update_rows = (
            await s.execute(
                text(
                    "SELECT o.id AS order_id, cp.id AS cp_id, o.product_id, o.channel_name "
                    "FROM samba_order o "
                    "JOIN samba_collected_product cp ON cp.site_product_id = o.product_id "
                    "WHERE o.source = 'playauto' AND o.collected_product_id IS NULL "
                    "AND o.product_id IS NOT NULL AND o.product_id != '' "
                    "ORDER BY o.product_id"
                )
            )
        ).fetchall()
        print(f"\nsite_product_id 매칭 결과: {len(update_rows):,}건")

        # 동일 product_id에 여러 CP가 있으면 샘플 확인
        from collections import Counter
        pid_cnt = Counter(r[2] for r in update_rows)
        dupes = [(pid, cnt) for pid, cnt in pid_cnt.items() if cnt > 1]
        if dupes:
            print(f"  product_id 중복 (여러 CP 매칭): {len(dupes)}종")
            for pid, cnt in dupes[:5]:
                print(f"    {pid}: {cnt}건")

        # 3) 샘플 확인
        if update_rows:
            print(f"\n매칭 샘플 5건:")
            for r in update_rows[:5]:
                print(f"  order_id={str(r[0])[:20]} cp_id={str(r[1])[:20]} product_id={r[2]} channel={r[3]}")

    if not update_rows:
        print("\nsite_product_id 매칭 없음")
        return

    # 4) DB 업데이트 (중복 product_id는 첫 번째 CP만 사용)
    seen_order_ids: set[str] = set()
    updates: list[tuple[str, str]] = []
    for r in update_rows:
        oid, cp_id = str(r[0]), str(r[1])
        if oid not in seen_order_ids:
            seen_order_ids.add(oid)
            updates.append((oid, cp_id))

    print(f"\n최종 업데이트 대상: {len(updates):,}건 (중복 제거됨)")

    async with get_write_session() as s:
        cnt = 0
        for oid, cp_id in updates:
            await s.execute(
                text(
                    "UPDATE samba_order "
                    "SET collected_product_id = :cp, updated_at = NOW() "
                    "WHERE id = :oid AND collected_product_id IS NULL"
                ),
                {"cp": cp_id, "oid": oid},
            )
            cnt += 1
            if cnt % 500 == 0:
                print(f"  {cnt:,}/{len(updates):,}...")
        await s.commit()

    print(f"\n완료: {cnt:,}건 업데이트")

    # 5) 잔여 확인
    async with get_read_session() as s:
        remaining = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL"
                )
            )
        ).scalar()
        by_channel = (
            await s.execute(
                text(
                    "SELECT channel_name, COUNT(*) FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL "
                    "GROUP BY channel_name ORDER BY 2 DESC LIMIT 5"
                )
            )
        ).fetchall()
    print(f"\n잔여 미등록 PlayAuto 주문: {remaining:,}건")
    for r in by_channel:
        print(f"  {r[0]}: {r[1]:,}건")


asyncio.run(main())
