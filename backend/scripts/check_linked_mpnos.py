"""linked PlayAuto 주문의 CP mpnos 패턴 확인 - 어떤 key로 매칭됐는지."""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text

from backend.db.orm import get_read_session

PA_ACCOUNT_ID = "ma_01KP0919YA061YX5PHH25KWJAK"


async def main() -> None:
    async with get_read_session() as s:
        # linked PlayAuto 주문에서 product_id + CP mpnos 비교
        rows = (
            await s.execute(
                text(
                    "SELECT o.product_id, o.channel_name, o.order_number, "
                    "cp.market_product_nos "
                    "FROM samba_order o "
                    "JOIN samba_collected_product cp ON cp.id = o.collected_product_id "
                    "WHERE o.source = 'playauto' AND o.collected_product_id IS NOT NULL "
                    "AND o.product_id IS NOT NULL AND o.product_id != '' "
                    "LIMIT 10"
                )
            )
        ).fetchall()

        print(f"linked PlayAuto 주문 샘플 {len(rows)}건:")
        for r in rows:
            pid = str(r[0] or "")
            mpnos = r[3] or {}
            if isinstance(mpnos, str):
                import json
                mpnos = json.loads(mpnos)
            in_mpnos = any(str(v) == pid for v in mpnos.values()) if isinstance(mpnos, dict) else False
            has_pa_key = PA_ACCOUNT_ID in mpnos if isinstance(mpnos, dict) else False
            pa_value = mpnos.get(PA_ACCOUNT_ID, "") if isinstance(mpnos, dict) else ""
            print(f"  product_id={pid!r} channel={r[1]}")
            print(f"    mpnos_has_pid={in_mpnos} has_PA_key={has_pa_key} PA_value={str(pa_value)[:30]!r}")
            if isinstance(mpnos, dict):
                for k, v in list(mpnos.items())[:5]:
                    print(f"    mpnos[{str(k)[:25]}] = {str(v)[:30]}")
            print()

        # 매칭 방법 분석: product_id가 mpnos에 있는 linked 주문 수
        cnt_pid_in_mpnos = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM samba_order o "
                    "JOIN samba_collected_product cp ON cp.id = o.collected_product_id "
                    "WHERE o.source = 'playauto' AND o.collected_product_id IS NOT NULL "
                    "AND o.product_id IS NOT NULL "
                    "AND EXISTS ("
                    "  SELECT 1 FROM jsonb_each_text(cp.market_product_nos) kv "
                    "  WHERE jsonb_typeof(cp.market_product_nos) = 'object' "
                    "  AND kv.value = o.product_id"
                    ")"
                )
            )
        ).scalar()
        cnt_total = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NOT NULL "
                    "AND product_id IS NOT NULL AND product_id != ''"
                )
            )
        ).scalar()
        print(f"linked 주문 중 product_id가 mpnos에 있는 비율: {cnt_pid_in_mpnos:,}/{cnt_total:,}")


asyncio.run(main())
