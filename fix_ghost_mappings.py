"""ghost 매핑 일괄 정리.

조건: registered_accounts에는 account_id가 있는데
      market_product_nos에 그 account_id 키가 없거나 빈 값인 행.

처리:
  - 11번가(account의 market_type='11st')인 경우 셀러센터에 살아있을 수 있어
    위험 → 일단 dry-run으로 카운트만 출력하고, 실제 정리는 --apply 인자로 실행.
  - 나머지 마켓은 dry-run에서 카운트, --apply에서 registered_accounts 제거.

사용:
  python /tmp/fix_ghost_mappings.py            # dry-run
  python /tmp/fix_ghost_mappings.py --apply    # 실제 제거
"""

import asyncio
import sys
import asyncpg
from backend.core.config import settings


async def main(apply: bool):
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        # 1. 활성 마켓 계정 모두 조회 (market_type별)
        accounts = await conn.fetch(
            "SELECT id, market_type, account_label FROM samba_market_account WHERE is_active = true"
        )
        print(f"활성 마켓 계정: {len(accounts)}개\n")

        total_ghost = 0
        per_market: dict[str, int] = {}
        per_account: dict[str, int] = {}

        for acc in accounts:
            aid = acc["id"]
            mtype = acc["market_type"]
            label = acc["account_label"]

            # ghost: registered_accounts @> [aid] AND
            #        (NOT market_product_nos ? aid OR market_product_nos->>aid = '')
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) c
                FROM samba_collected_product
                WHERE registered_accounts @> $1::jsonb
                  AND (
                    market_product_nos IS NULL
                    OR NOT (market_product_nos ? $2)
                    OR (market_product_nos ->> $2) = ''
                  )
                """,
                f'["{aid}"]',
                aid,
            )
            cnt = row["c"]
            if cnt:
                per_market[mtype] = per_market.get(mtype, 0) + cnt
                per_account[f"{mtype}/{label}({aid[-6:]})"] = cnt
                total_ghost += cnt

        print("=== ghost 매핑 카운트 (market_type별) ===")
        for k, v in sorted(per_market.items(), key=lambda x: -x[1]):
            print(f"  {k:<12} {v:>6}")
        print(f"\n  TOTAL        {total_ghost:>6}")

        print("\n=== ghost 매핑 카운트 (계정별 상위 20) ===")
        for k, v in sorted(per_account.items(), key=lambda x: -x[1])[:20]:
            print(f"  {k:<60} {v:>6}")

        if not apply:
            print(
                "\n[dry-run] --apply 인자 추가 시 registered_accounts에서 제거됩니다."
            )
            return

        # 2. 실제 제거
        print("\n=== --apply 실행: ghost 매핑 정리 시작 ===")
        cleared_total = 0
        for acc in accounts:
            aid = acc["id"]
            mtype = acc["market_type"]
            # registered_accounts에서 aid 제거 (jsonb 연산자 -)
            result = await conn.execute(
                """
                UPDATE samba_collected_product
                SET registered_accounts = registered_accounts - $2::text,
                    status = CASE
                        WHEN jsonb_array_length(registered_accounts - $2::text) = 0 THEN 'collected'
                        ELSE status
                    END,
                    updated_at = NOW()
                WHERE registered_accounts @> $1::jsonb
                  AND (
                    market_product_nos IS NULL
                    OR NOT (market_product_nos ? $2)
                    OR (market_product_nos ->> $2) = ''
                  )
                """,
                f'["{aid}"]',
                aid,
            )
            # asyncpg 결과 형식: 'UPDATE N'
            try:
                n = int(result.split()[-1])
            except (ValueError, IndexError):
                n = 0
            if n:
                cleared_total += n
                print(f"  {mtype:<12} {acc['account_label']:<30} 정리 {n}건")

        print(f"\n총 {cleared_total}건 정리 완료.")
    finally:
        await conn.close()


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    asyncio.run(main(apply))
