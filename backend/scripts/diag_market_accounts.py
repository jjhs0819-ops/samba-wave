"""GS이숍/현대H몰/KT알파쇼핑 마켓 계정 ID + product_id 매칭 가능성 확인."""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text

from backend.db.orm import get_read_session


async def main() -> None:
    async with get_read_session() as s:
        # PlayAuto 솔루션을 통해 등록하는 마켓 계정 조회
        mkt_accts = (
            await s.execute(
                text(
                    "SELECT id, market_type, account_label "
                    "FROM samba_market_account "
                    "WHERE market_type IN ('gsshop', 'hyundaih', 'ktalpha', 'playauto') "
                    "ORDER BY market_type"
                )
            )
        ).fetchall()

        print("마켓 계정 목록:")
        for a in mkt_accts:
            print(f"  id={a[0]} type={a[1]} label={a[2]}")

        # 미등록 주문 product_id 샘플
        pid_samples = (
            await s.execute(
                text(
                    "SELECT DISTINCT product_id, channel_name "
                    "FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL "
                    "AND product_id IS NOT NULL AND product_id != '' "
                    "LIMIT 10"
                )
            )
        ).fetchall()
        print(f"\n미등록 주문 product_id 샘플:")
        for r in pid_samples:
            print(f"  product_id={r[0]!r} channel={r[1]}")

        # product_id가 mpnos에 value로 있는 CP 있는지 확인 (JSONB 텍스트 검색)
        # 샘플 product_id 하나로 테스트
        if pid_samples:
            test_pid = pid_samples[0][0]
            # GS이숍 마켓 계정 목록에서 key 추출해서 mpnos 검색
            hit = (
                await s.execute(
                    text(
                        "SELECT id, market_product_nos "
                        "FROM samba_collected_product "
                        "WHERE market_product_nos::text LIKE :pat "
                        "LIMIT 3"
                    ),
                    {"pat": f'%"{test_pid}"%'},
                )
            ).fetchall()
            print(f"\nproduct_id={test_pid!r} mpnos 검색 결과: {len(hit)}개")
            for h in hit:
                print(f"  CP={h[0]} mpnos={str(h[1])[:200]}")

        # 전체 미등록 주문 product_id 100개로 mpnos 검색 (IN 방식)
        all_pids = (
            await s.execute(
                text(
                    "SELECT DISTINCT product_id FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL "
                    "AND product_id IS NOT NULL LIMIT 500"
                )
            )
        ).fetchall()
        pid_list = [r[0] for r in all_pids]
        print(f"\n미등록 주문 product_id 총 {len(pid_list)}종 (최대 500개 샘플)")

        # mpnos value에 product_id가 있는 CP 수 (JSONB 역방향 조회)
        # market_product_nos의 모든 value를 풀어서 조회
        cnt = (
            await s.execute(
                text(
                    "SELECT COUNT(DISTINCT cp.id) "
                    "FROM samba_collected_product cp, "
                    "jsonb_each_text(cp.market_product_nos) kv "
                    "WHERE jsonb_typeof(cp.market_product_nos) = 'object' "
                    "AND kv.value = ANY(:pids)"
                ),
                {"pids": pid_list},
            )
        ).scalar()
        print(f"product_id가 mpnos에 있는 CP 수: {cnt:,}개")

        # 실제 매핑 샘플 5개
        samples = (
            await s.execute(
                text(
                    "SELECT cp.id, kv.key, kv.value "
                    "FROM samba_collected_product cp, "
                    "jsonb_each_text(cp.market_product_nos) kv "
                    "WHERE jsonb_typeof(cp.market_product_nos) = 'object' "
                    "AND kv.value = ANY(:pids) "
                    "LIMIT 5"
                ),
                {"pids": pid_list},
            )
        ).fetchall()
        for r in samples:
            print(f"  CP={r[0]} acct_key={r[1]} product_id={r[2]}")


asyncio.run(main())
