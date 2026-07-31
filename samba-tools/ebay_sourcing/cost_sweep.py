"""번장 원가 전수조사 + 판매가 재계산 [컨테이너 실행].

원가 = 번장 현재가 + 배송비(shippingSpecs 중 **최저** 옵션. 반값택배가 보통 절반 이하라
DEFAULT만 보면 과대계상돼 판매가가 부풀고 경쟁력을 잃는다. freeShipping이면 0)
판매가 = calc_market_price(원가, 정책)
  ← eBay 플러그인이 sale_price 를 그대로 판매가로 쓰므로 이 값을 안 넣으면 원가에 팔린다.

소스가 SELLING 이 아니면 전송하지 않고 SOLDOUT 으로만 표시한다(대체 매칭은 사람이 판단).

실행:
  docker cp samba-tools/ebay_sourcing/cost_sweep.py local-samba-api-1:/tmp/cost_sweep.py
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/cost_sweep.py
"""

import asyncio
import sys
import io
import json
import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

H = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://m.bunjang.co.kr/",
}
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
TEN = "tn_01KRX6H1Q97JGPXRPB011985QT"


async def bj(c, pid):
    r = await c.get(f"https://api.bunjang.co.kr/api/pms/v1/products/{pid}/detail/web")
    p = r.json().get("data", {}).get("product", {})
    tr = p.get("trade") or {}
    # [중요] 배송비는 최저 옵션 기준. DEFAULT(일반택배)만 보면 과대계상 →
    # 판매가가 부풀어 경쟁력 상실. GS_HALF_PRICE/CU_THRIFTY(반값택배)가 보통 절반 이하.
    if tr.get("freeShipping"):
        fee = 0
    else:
        _specs = tr.get("shippingSpecs") or {}
        _fees = [int(v.get("fee") or 0) for v in _specs.values() if isinstance(v, dict)]
        fee = min(_fees) if _fees else 0
    return p.get("saleStatus"), int(p.get("price") or 0), fee


async def main():
    import backend.main  # noqa
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from backend.domain.samba.shipment.service import calc_market_price
    from sqlalchemy import text as t
    from sqlmodel import select

    tok = current_tenant_id.set(TEN)
    async with get_write_session() as s:
        rows = (
            await s.execute(
                t(
                    "SELECT id, site_product_id FROM samba_collected_product "
                    "WHERE source_site='BUNJANG' AND registered_accounts::text LIKE '%ma_01KXQCB67%' "
                    "ORDER BY id"
                )
            )
        ).fetchall()
    print("대상:", len(rows))

    async with httpx.AsyncClient(timeout=20, headers=H) as c:
        for pid_db, bpid in rows:
            try:
                st, price, fee = await bj(c, bpid)
            except Exception as e:
                print(f"SKIP {bpid} 조회실패 {str(e)[:40]}")
                continue
            if st != "SELLING":
                print(f"SOLDOUT {bpid} status={st}")
                continue
            newcost = price + fee
            try:
                async with get_write_session() as s:
                    acc = (
                        (
                            await s.execute(
                                select(SambaMarketAccount).where(
                                    SambaMarketAccount.id == KV
                                )
                            )
                        )
                        .scalars()
                        .first()
                    )
                    p = (
                        (
                            await s.execute(
                                select(SambaCollectedProduct).where(
                                    SambaCollectedProduct.id == pid_db
                                )
                            )
                        )
                        .scalars()
                        .first()
                    )
                    pr, mp = (
                        await s.execute(
                            t(
                                "SELECT pricing,market_policies FROM samba_policy WHERE id=:i"
                            ),
                            {"i": p.applied_policy_id},
                        )
                    ).first()
                    pr = pr if isinstance(pr, dict) else json.loads(pr or "{}")
                    mp = mp if isinstance(mp, dict) else json.loads(mp or "{}")
                    newprice = calc_market_price(float(newcost), pr, "ebay", mp)
                    oldc, oldp = int(p.cost or 0), int(p.sale_price or 0)
                    p.cost = float(newcost)
                    p.original_price = float(newcost)
                    p.sale_price = float(newprice)
                    s.add(p)
                    await s.flush()
                    nm = p.name_en or ""
                    cat = (
                        "183455"
                        if "Booster Box" in nm
                        else (
                            "108857"
                            if p.applied_policy_id
                            in ("pol_kpopcard_v1", "pol_kpopgoods_v1")
                            else "183454"
                        )
                    )
                    res = await dispatch_to_market(
                        s,
                        "ebay",
                        p.model_dump(),
                        category_id=cat,
                        account=acc,
                        existing_product_no=str((p.market_product_nos or {}).get(KV)),
                    )
                    ok = res.get("success")
                    print(
                        f"{'OK' if ok else 'FAIL'} 원가{oldc}→{newcost}(배송{fee}) 판매{oldp}→{int(newprice)} | {nm[:36]}"
                    )
                    if ok:
                        await s.commit()
                    else:
                        await s.rollback()
            except Exception as e:
                print(f"ERR {bpid} {str(e)[:60]}")
    current_tenant_id.reset(tok)


asyncio.run(main())
