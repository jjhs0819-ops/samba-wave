"""PlayAuto MasterCode(AM...) → mpnos global 매칭 확인."""

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text  # noqa: E402

from backend.db.orm import get_read_session  # noqa: E402

# 로그에서 추출한 미등록 주문의 실제 MasterCode 샘플
SAMPLE_MASTER_CODES = [
    "AM0528125320394",  # LM3EN0S (룰루레몬, 미등록)
    "AM0516174500952",  # KT알파쇼핑 크록스
    "AM0605165456298",  # GS이숍 게스언더웨어
    "AM0611194740196",  # 현대H몰 스파오
    "AM0516130332302",  # GS이숍 리바이스
]


async def main() -> None:
    async with get_read_session() as s:
        PA_ID = "ma_01KP0919YA061YX5PHH25KWJAK"

        for mc in SAMPLE_MASTER_CODES:
            # mpnos value = AM... 직접 조회
            rows = (
                await s.execute(
                    text(
                        "SELECT cp.id, cp.name, cp.market_product_nos->:kid AS pa_val "
                        "FROM samba_collected_product cp "
                        "WHERE cp.market_product_nos ? :kid "
                        "AND (cp.market_product_nos->:kid)::text = :val"
                    ),
                    {"kid": PA_ID, "val": f'"{mc}"'},
                )
            ).fetchall()
            print(f"MasterCode={mc}: {len(rows)}건")
            for r in rows:
                print(f"  → {r[0]} {str(r[1] or '')[:50]}")

        # 전체 AM... 코드가 있는 CP 수 vs 미등록 주문 AM 코드 교집합
        # 로그 추가 샘플 (위 5개 외 더 많이)
        unlinked_orders = (
            await s.execute(
                text(
                    "SELECT o.product_id FROM samba_order o "
                    "WHERE o.source = 'playauto' "
                    "AND o.collected_product_id IS NULL "
                    "AND o.product_id IS NOT NULL "
                    "LIMIT 5"
                )
            )
        ).fetchall()
        print(f"\n미등록 주문 product_id: {[r[0] for r in unlinked_orders]}")

        # AM... 형식 mpnos 전체 샘플 10개 - 어떤 형식이 저장돼 있는지
        am_vals = (
            await s.execute(
                text(
                    "SELECT (cp.market_product_nos->:kid)::text AS v "
                    "FROM samba_collected_product cp "
                    "WHERE cp.market_product_nos ? :kid "
                    "AND (cp.market_product_nos->:kid)::text LIKE '\"AM%' "
                    "LIMIT 5"
                ),
                {"kid": PA_ID},
            )
        ).fetchall()
        print(f"\nmpnos AM... 형식 샘플: {[r[0] for r in am_vals]}")


asyncio.run(main())
