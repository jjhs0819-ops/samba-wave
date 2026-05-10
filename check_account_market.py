"""케이스 2 마켓 삭제 대상 account → market_type 매핑"""
import asyncio
import asyncpg
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port,
        user=settings.write_db_user, password=settings.write_db_password,
        database=settings.write_db_name, ssl=False,
    )

    targets = [
        ("ma_01KP0919YA061YX5PHH25KWJAK", 1791),
        ("ma_01KM5046TVPHYBAWZNR4KV65MB", 73),
        ("ma_01KM2K57Z8BQY984WC4HE93VQJ", 14),
    ]
    print("=== account → market_type 매핑 ===")
    for acc_id, cnt in targets:
        row = await conn.fetchrow(
            "SELECT id, market_type, market_name, seller_id FROM samba_market_account WHERE id=$1",
            acc_id,
        )
        if row:
            print(f"  {acc_id} → market_type={row['market_type']} name={row['market_name']} seller={row['seller_id']} (삭제 호출 {cnt:,}건)")
        else:
            print(f"  {acc_id} → 계정 없음! (삭제 호출 {cnt:,}건)")

    # 전체 마켓별 합계
    print("\n=== 마켓별 삭제 호출 합계 추정 ===")
    rows = await conn.fetch(
        """
        SELECT id, market_type, market_name, seller_id
        FROM samba_market_account
        WHERE id = ANY($1::text[])
        """,
        [t[0] for t in targets],
    )
    by_market: dict[str, int] = {}
    for t in targets:
        for r in rows:
            if r['id'] == t[0]:
                by_market[r['market_type']] = by_market.get(r['market_type'], 0) + t[1]
                break
    for mt, c in sorted(by_market.items(), key=lambda x: -x[1]):
        print(f"  {mt}: {c:,}건")

    await conn.close()


asyncio.run(main())
