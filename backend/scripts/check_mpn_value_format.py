"""market_product_nos PlayAuto 계정 키 실제 저장값 확인."""

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text  # noqa: E402

from backend.db.orm import get_read_session  # noqa: E402

PA_ID = "ma_01KP0919YA061YX5PHH25KWJAK"


async def main() -> None:
    async with get_read_session() as s:
        # PlayAuto 계정 key 실제 저장값 샘플
        vals = (
            await s.execute(
                text(
                    "SELECT cp.id, "
                    "       cp.market_product_nos->:kid AS pa_val, "
                    "       cp.name "
                    "FROM samba_collected_product cp "
                    "WHERE cp.market_product_nos ? :kid "
                    "LIMIT 10"
                ),
                {"kid": PA_ID},
            )
        ).fetchall()
        print(f"PlayAuto 계정 mpnos 저장값 샘플:")
        for r in vals:
            print(f"  cp_id={r[0]} pa_val={r[1]!r} name={str(r[2] or '')[:40]}")

        # 미등록 주문 product_id 형식 vs 저장값 비교
        print("\n미등록 주문 product_id 샘플:")
        pids = ["1103003339007", "1103003841002", "1103020246002", "1109537394005"]
        for pid in pids:
            # 정확 매칭
            exact = (
                await s.execute(
                    text(
                        "SELECT COUNT(*) FROM samba_collected_product "
                        "WHERE (market_product_nos->:kid)::text = :val"
                    ),
                    {"kid": PA_ID, "val": f'"{pid}"'},
                )
            ).scalar()
            # 접두어 매칭 (13자리 중 앞 10자리 = 마스터코드 가설)
            prefix = pid[:10]
            prefix_hit = (
                await s.execute(
                    text(
                        "SELECT COUNT(*) FROM samba_collected_product "
                        "WHERE jsonb_typeof(market_product_nos) = 'object' "
                        "AND market_product_nos->:kid IS NOT NULL "
                        "AND (market_product_nos->:kid)::text LIKE :pat"
                    ),
                    {"kid": PA_ID, "pat": f'"{prefix}%"'},
                )
            ).scalar()
            print(f"  pid={pid} exact={exact} prefix10={prefix_hit}")

        # 저장값 길이 분포
        len_dist = (
            await s.execute(
                text(
                    "SELECT LENGTH((cp.market_product_nos->:kid)::text)-2 AS vlen, "
                    "       COUNT(*) "
                    "FROM samba_collected_product cp "
                    "WHERE cp.market_product_nos ? :kid "
                    "GROUP BY vlen ORDER BY COUNT(*) DESC LIMIT 10"
                ),
                {"kid": PA_ID},
            )
        ).fetchall()
        print(f"\n저장값 길이 분포:")
        for r in len_dist:
            print(f"  길이={r[0]}: {r[1]:,}건")


asyncio.run(main())
