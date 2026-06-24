"""PlayAuto MPN 매칭 상세 진단 — 실제 market_product_nos 값 vs 주문 product_id 비교."""

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text  # noqa: E402

from backend.db.orm import get_read_session  # noqa: E402


async def main() -> None:
    async with get_read_session() as s:
        # 1) GS이숍 PlayAuto 채널 계정 ID 확인
        ch_rows = (
            await s.execute(
                text(
                    "SELECT id, market_type, account_label "
                    "FROM samba_market_account "
                    "WHERE market_type = 'playauto' "
                    "LIMIT 5"
                )
            )
        ).fetchall()
        print("PlayAuto 채널 계정:")
        for r in ch_rows:
            print(f"  id={r[0]} type={r[1]} label={r[2]}")

        # 2) 이 PlayAuto 채널 계정 ID가 market_product_nos key에 있는 CP 수
        pa_ids = [str(r[0]) for r in ch_rows]
        if pa_ids:
            for pa_id in pa_ids:
                cnt = (
                    await s.execute(
                        text(
                            "SELECT COUNT(*) FROM samba_collected_product "
                            "WHERE jsonb_typeof(market_product_nos) = 'object' "
                            "AND market_product_nos ? :kid"
                        ),
                        {"kid": pa_id},
                    )
                ).scalar()
                print(f"  market_product_nos[{pa_id}] 있는 CP: {cnt:,}개")

        # 3) 실제 linked PlayAuto 주문의 product_id vs market_product_nos 비교
        linked_sample = (
            await s.execute(
                text(
                    "SELECT o.product_id, o.channel_id, o.collected_product_id, "
                    "       cp.market_product_nos "
                    "FROM samba_order o "
                    "JOIN samba_collected_product cp ON cp.id = o.collected_product_id "
                    "WHERE o.source = 'playauto' "
                    "AND o.collected_product_id IS NOT NULL "
                    "AND o.product_id IS NOT NULL "
                    "AND jsonb_typeof(cp.market_product_nos) = 'object' "
                    "LIMIT 5"
                )
            )
        ).fetchall()
        print(f"\nLinked PlayAuto 주문 샘플 {len(linked_sample)}건:")
        for r in linked_sample:
            mpnos = r[3] or {}
            print(
                f"  product_id={str(r[0]):<20s} channel={str(r[1]):<36s}"
            )
            # product_id가 market_product_nos 어디에 있는지 확인
            pid = str(r[0] or "")
            found = [f"{k}={v}" for k, v in mpnos.items() if str(v) == pid]
            print(f"    mpnos 중 일치: {found if found else '없음'}")
            print(f"    mpnos 키 목록: {list(mpnos.keys())[:5]}")

        # 4) 미등록 주문 샘플의 product_id가 어떤 CP의 mpnos에도 없는지 확인
        unlinked_pids = (
            await s.execute(
                text(
                    "SELECT DISTINCT product_id FROM samba_order "
                    "WHERE source = 'playauto' AND collected_product_id IS NULL "
                    "AND product_id IS NOT NULL AND product_id != '' "
                    "LIMIT 5"
                )
            )
        ).fetchall()
        print(f"\n미등록 product_id 샘플에 해당하는 CP 찾기:")
        for r in unlinked_pids:
            pid = str(r[0]).strip()
            hits = (
                await s.execute(
                    text(
                        "SELECT cp.id, cp.name "
                        "FROM samba_collected_product cp, "
                        "     jsonb_each_text(cp.market_product_nos) kv "
                        "WHERE jsonb_typeof(cp.market_product_nos) = 'object' "
                        "AND kv.value = :pid"
                    ),
                    {"pid": pid},
                )
            ).fetchall()
            print(f"  pid={pid}: {len(hits)}건 히트")
            for h in hits[:2]:
                print(f"    → {h[0]} {str(h[1] or '')[:40]}")


asyncio.run(main())
