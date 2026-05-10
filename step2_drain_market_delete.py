"""2단계: 마켓 삭제 큐 drain

- playauto: API 삭제 불가 → status='skipped_playauto' 마킹만
- lottehome / smartstore: delete_from_markets 호출
"""
import asyncio
import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession
from backend.core.config import settings
from backend.db.orm import get_write_sessionmaker
from backend.domain.samba.shipment.service import SambaShipmentService
from backend.domain.samba.shipment.repository import SambaShipmentRepository


async def main():
    # 이벤트 루프 안에서 sessionmaker 초기화
    AsyncSessionLocal = get_write_sessionmaker()

    raw = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port,
        user=settings.write_db_user, password=settings.write_db_password,
        database=settings.write_db_name, ssl=False,
    )
    # playauto skip 되돌리기 — 재고0+취소대기 처리 가능 (plugins/markets/playauto.py:540)
    res = await raw.execute(
        """
        UPDATE samba_dedupe_market_delete_queue
        SET status='pending', processed_at=NULL
        WHERE status='skipped_playauto'
        """
    )
    print(f"[playauto pending 복귀] {res}")

    # 처리 대상 (lottehome/smartstore)
    pending = await raw.fetch(
        """
        SELECT queue_id, collected_product_id, account_id, market_type, market_product_no, source_site, site_product_id
        FROM samba_dedupe_market_delete_queue
        WHERE status='pending'
        ORDER BY queue_id
        """
    )
    print(f"[처리 대상] {len(pending)}건 (lottehome/smartstore)")
    await raw.close()

    # 2) 한 건씩 마켓 삭제 호출
    success = 0
    failed = 0
    for i, q in enumerate(pending, 1):
        cpid = q['collected_product_id']
        aid = q['account_id']
        try:
            async with AsyncSessionLocal() as session:  # type: AsyncSession
                svc = SambaShipmentService(SambaShipmentRepository(session), session)
                result = await svc.delete_from_markets(
                    product_ids=[cpid],
                    target_account_ids=[aid],
                    log_to_buffer=False,
                )
                # delete_from_markets는 results 리스트 반환
                rs = (result.get("results") or [{}])[0]
                d_results = rs.get("delete_results", {})
                status = d_results.get(aid, "unknown")
                if status == "success":
                    success += 1
                    upd_status = 'success'
                    err = None
                else:
                    failed += 1
                    upd_status = 'failed'
                    err = str(status)[:500]
                # 큐 업데이트
                from sqlalchemy import text
                await session.execute(
                    text(
                        "UPDATE samba_dedupe_market_delete_queue "
                        "SET status=:s, attempts=attempts+1, last_error=:e, processed_at=NOW() "
                        "WHERE queue_id=:q"
                    ),
                    {"s": upd_status, "e": err, "q": q['queue_id']},
                )
                await session.commit()
            print(f"  [{i}/{len(pending)}] {q['market_type']} {q['source_site']}/{q['site_product_id']} mpn={q['market_product_no']} → {upd_status}")
        except Exception as e:
            failed += 1
            print(f"  [{i}/{len(pending)}] EXC: {e}")
            try:
                async with AsyncSessionLocal() as session2:
                    from sqlalchemy import text
                    await session2.execute(
                        text(
                            "UPDATE samba_dedupe_market_delete_queue "
                            "SET status='failed', attempts=attempts+1, last_error=:e, processed_at=NOW() "
                            "WHERE queue_id=:q"
                        ),
                        {"e": str(e)[:500], "q": q['queue_id']},
                    )
                    await session2.commit()
            except Exception:
                pass

    print(f"\n=== 2단계 완료 ===")
    print(f"  성공: {success}")
    print(f"  실패: {failed}")
    print(f"  playauto skip: 1,791")


asyncio.run(main())
