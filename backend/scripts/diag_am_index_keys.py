"""AM코드가 저장된 mpnos key 패턴 조사 + 미등록 주문 대상 AM코드 찾기."""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text

from backend.db.orm import get_read_session

PA_ACCOUNT_ID = "ma_01KP0919YA061YX5PHH25KWJAK"


async def main() -> None:
    async with get_read_session() as s:
        # 1) AM코드가 어떤 key들에 저장됐는지 확인 (AM으로 시작하는 value의 key 분포)
        am_keys = (
            await s.execute(
                text(
                    "SELECT kv.key, COUNT(*) as cnt "
                    "FROM samba_collected_product cp, jsonb_each_text(cp.market_product_nos) kv "
                    "WHERE jsonb_typeof(cp.market_product_nos) = 'object' "
                    "AND kv.value LIKE 'AM%' "
                    "GROUP BY kv.key ORDER BY cnt DESC LIMIT 10"
                )
            )
        ).fetchall()
        print("AM코드가 저장된 mpnos key 분포:")
        for r in am_keys:
            print(f"  key={r[0]} cnt={r[1]:,}")

        # 2) backfill_playauto_by_prodcode에서 찾은 MasterCode 125건이
        #    어느 key로 있는지 확인 (PlayAuto API 재폴링 대신 랜덤 AM코드로 테스트)
        # 먼저 playauto api로 AM코드 몇 개 샘플
        # → 직접 테스트: 미등록 주문 product_id로 PlayAuto order MasterCode 다시 확인
        # 최근 미등록 주문 product_id 10개
        pids = (
            await s.execute(
                text(
                    "SELECT DISTINCT product_id FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL "
                    "AND product_id IS NOT NULL LIMIT 10"
                )
            )
        ).fetchall()
        pid_list = [r[0] for r in pids]
        print(f"\n미등록 주문 product_id 샘플: {pid_list[:5]}")

        # 3) 이 product_id들로 모든 AM코드 key에서 검색
        for key_row in am_keys:
            key = key_row[0]
            # 이 key의 value가 product_id인 CP 있는지
            cnt = (
                await s.execute(
                    text(
                        "SELECT COUNT(*) FROM samba_collected_product cp "
                        "WHERE jsonb_typeof(cp.market_product_nos) = 'object' "
                        "AND (cp.market_product_nos->>:k) = ANY(:pids)"
                    ),
                    {"k": key, "pids": pid_list},
                )
            ).scalar()
            if cnt:
                print(f"  key={key} → {cnt}개 매칭!")

        # 4) 전체 mpnos 역방향 검색 (AM코드 key 무관)
        cnt2 = (
            await s.execute(
                text(
                    "SELECT COUNT(DISTINCT cp.id) "
                    "FROM samba_collected_product cp, jsonb_each_text(cp.market_product_nos) kv "
                    "WHERE jsonb_typeof(cp.market_product_nos) = 'object' "
                    "AND kv.value = ANY(:pids)"
                ),
                {"pids": pid_list},
            )
        ).scalar()
        print(f"\n전체 mpnos 역방향 검색 결과: {cnt2}개")

        # 5) GS이숍 소싱처 CP 확인 (source_site='gsshop')
        gsshop_cnt = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM samba_collected_product "
                    "WHERE source_site = 'gsshop'"
                )
            )
        ).scalar()
        print(f"\nGS이숍 소싱처 CP 수: {gsshop_cnt:,}개")

        # 6) 미등록 주문 product_id와 GS이숍 소싱처 CP site_product_id 비교
        gs_match = (
            await s.execute(
                text(
                    "SELECT COUNT(DISTINCT o.id) "
                    "FROM samba_order o "
                    "JOIN samba_collected_product cp "
                    "ON cp.source_site = 'gsshop' AND cp.site_product_id = o.product_id "
                    "WHERE o.source = 'playauto' AND o.collected_product_id IS NULL"
                )
            )
        ).scalar()
        print(f"GS이숍 소싱처 CP.site_product_id 매칭: {gs_match:,}건")


asyncio.run(main())
