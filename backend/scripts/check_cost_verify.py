import asyncio
import sys

sys.path.insert(0, "/app")
from backend.db.orm import get_read_session
from sqlalchemy import text


async def main():
    async with get_read_session() as sess:
        for tbl in ["samba_collected_product", "samba_product"]:
            r = await sess.execute(
                text(
                    f"SELECT source_site, COUNT(*), MAX(updated_at), COUNT(CASE WHEN cost>0 THEN 1 END)"
                    f" FROM {tbl}"
                    f" WHERE source_site IN ('SSG','ABCmart','LOTTEON')"
                    f" GROUP BY source_site ORDER BY source_site"
                )
            )
            print(f"\n=== {tbl} ===")
            for row in r.fetchall():
                print(
                    f"  {row[0]}: 전체={row[1]}건 | 최근갱신={str(row[2])[5:16]} | cost>0={row[3]}건"
                )

        # 최근 cost 갱신된 samba_collected_product 샘플
        r2 = await sess.execute(
            text(
                "SELECT source_site, id, sale_price, cost, updated_at"
                " FROM samba_collected_product"
                " WHERE source_site IN ('SSG','ABCmart','LOTTEON')"
                " AND cost > 0"
                " ORDER BY updated_at DESC LIMIT 15"
            )
        )
        print("\n=== samba_collected_product 최근 cost 갱신 15개 ===")
        for row in r2.fetchall():
            site, pid, sale, cost, upd = row
            diff = int(sale - cost) if sale and cost else 0
            pct = round(diff / sale * 100, 1) if sale else 0
            flag = "OK" if diff >= 0 else "NG"
            print(
                f"  {flag} [{site}] {pid} | sale={int(sale) if sale else 0} | cost={int(cost) if cost else 0} | margin={diff}({pct}%) | {str(upd)[5:19]}"
            )


asyncio.run(main())
