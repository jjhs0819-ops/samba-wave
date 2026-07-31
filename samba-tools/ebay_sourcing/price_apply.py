"""수집된 번장 새 가격을 원가·판매가·eBay 리스팅에 반영 [컨테이너 실행].

번장 API 는 컨테이너에서 rate-limit 로 막힌다(2026-07-25). 그래서 가격 수집은
호스트에서 sweep.py(웨일 브라우저)로 하고, 여기서는 그 결과(price_updates.json)만
읽어 반영한다 — 번장을 다시 호출하지 않는다.

price_updates.json 형식: [{"sku":"cp_...","new":33000,"old":38000}, ...]

규칙: 가격만 손댄다(재고·하자고지·사진은 유지). dispatch 가 기존 리스팅 재고를 지킨다.

실행:
  docker cp samba-tools/ebay_sourcing/price_updates.json local-samba-api-1:/tmp/
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/price_apply.py [--dry]
"""

import asyncio
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
MAX_COST = 300000  # 사용자 지정: 원가 30만원 이상은 반영 안 함


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from backend.domain.samba.shipment.service import calc_market_price
    from sqlalchemy import text as t
    from sqlmodel import select

    dry = "--dry" in sys.argv
    updates = json.load(open("/tmp/price_updates.json", encoding="utf-8"))
    tok = current_tenant_id.set(TENANT)
    ok = skip = fail = 0
    try:
        async with get_write_session() as s:
            acc = (
                (
                    await s.execute(
                        select(SambaMarketAccount).where(SambaMarketAccount.id == KV)
                    )
                )
                .scalars()
                .first()
            )
            for u in updates:
                sku, new_cost = u["sku"], int(u["new"])
                p = (
                    (
                        await s.execute(
                            select(SambaCollectedProduct).where(
                                SambaCollectedProduct.id == sku
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if not p:
                    continue
                lid = (p.market_product_nos or {}).get(KV, "")
                nm = (p.name_en or p.name or "")[:36]
                if not lid:
                    continue
                if new_cost >= MAX_COST:
                    skip += 1
                    print(f"SKIP(원가 {new_cost:,}) {nm}")
                    continue
                _pr, _mp = (
                    await s.execute(
                        t(
                            "SELECT pricing, market_policies FROM samba_policy WHERE id=:i"
                        ),
                        {"i": p.applied_policy_id},
                    )
                ).first()
                _pr = _pr if isinstance(_pr, dict) else json.loads(_pr or "{}")
                _mp = _mp if isinstance(_mp, dict) else json.loads(_mp or "{}")
                sale = float(
                    calc_market_price(float(new_cost), _pr, "ebay", _mp) or new_cost
                )
                print(
                    f"{'DRY' if dry else 'RUN'} {nm} | {int(p.cost or 0):,}→{new_cost:,} | 판매 {int(sale):,}"
                )
                if dry:
                    continue
                p.cost = float(new_cost)
                p.original_price = float(new_cost)
                p.sale_price = sale
                s.add(p)
                await s.commit()
                cat = (
                    "108857"
                    if p.applied_policy_id in ("pol_kpopcard_v1", "pol_kpopgoods_v1")
                    else "183454"
                )
                try:
                    res = await dispatch_to_market(
                        s,
                        "ebay",
                        p.model_dump(),
                        category_id=cat,
                        account=acc,
                        existing_product_no=lid,
                    )
                    if res.get("success"):
                        ok += 1
                    else:
                        fail += 1
                        print(f"   eBay실패 {str(res.get('message'))[:60]}")
                except Exception as e:
                    fail += 1
                    print(f"   예외 {str(e)[:60]}")
            print(
                f"\n완료: 갱신 {ok} / 상한초과 {skip} / 실패 {fail} / 대상 {len(updates)}"
            )
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
