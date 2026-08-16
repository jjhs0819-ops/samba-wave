"""번장소싱+eBay등록+판매이력0 상품 일괄 삭제(마켓삭제+DB삭제) [컨테이너 실행].

collector.py::bulk_delete_products 로직 재사용(리셀보호/스냅샷/마켓삭제 실패시 DB삭제 보류 포함).
"""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.core.cache import cache
    from backend.domain.samba.collector.model import SambaCollectedProduct as CP
    from backend.domain.samba.shipment.repository import SambaShipmentRepository as SR
    from backend.domain.samba.shipment.service import SambaShipmentService as SS
    from backend.api.v1.routers.samba.collector import (
        _protect_resell_linked,
        _snapshot_cp_to_orders,
        _get_services,
    )
    from sqlmodel import col, select
    from sqlalchemy import text as t

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            rows = await s.execute(t("""
                SELECT cp.id
                FROM samba_collected_product cp
                WHERE cp.source_site = 'BUNJANG'
                  AND cp.registered_accounts::text LIKE :kv
                  AND NOT EXISTS (
                      SELECT 1 FROM samba_order o
                      WHERE o.source = 'ebay' AND o.collected_product_id = cp.id
                  )
            """), {"kv": f"%{KV}%"})
            target_ids = [r[0] for r in rows.fetchall()]
            print(f"대상 {len(target_ids)}건")

            target_ids, protected = await _protect_resell_linked(s, target_ids)
            print(f"리셀보호 제외 {len(protected)}건, 실제 대상 {len(target_ids)}건")
            if not target_ids:
                print("삭제할 것 없음")
                return

            await _snapshot_cp_to_orders(s, target_ids)
            await s.commit()

            stmt = select(CP).where(col(CP.id).in_(target_ids))
            prows = (await s.execute(stmt)).scalars().all()

            market_pids, all_accs, seen = [], [], set()
            for p in prows:
                reg = list(getattr(p, "registered_accounts", None) or [])
                if reg:
                    market_pids.append(p.id)
                    for a in reg:
                        if a not in seen:
                            seen.add(a)
                            all_accs.append(a)

            failed_pids = set()
            if market_pids and all_accs:
                ship_svc = SS(SR(s), s)
                del_r = await ship_svc.delete_from_markets(market_pids, all_accs)
                for entry in del_r.get("results") or []:
                    dr = entry.get("delete_results") or {}
                    if dr and entry.get("success_count", 0) < len(dr):
                        failed_pids.add(entry.get("product_id", ""))
                        print(f"  마켓삭제 실패 pid={entry.get('product_id')}: {dr}")

            deletable = [pid for pid in target_ids if pid not in failed_pids]
            svc = _get_services(s)
            deleted = await svc.bulk_delete_collected_products(deletable)
            await cache.clear_pattern("products:*")

            print(f"완료: DB삭제 {deleted}건, 마켓삭제실패로 보류 {len(failed_pids)}건")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
