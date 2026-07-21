"""가격변동 배치 갱신 = 원가만 바꿔 revise [컨테이너 실행, 수수료 0].

소스는 SELLING 유지(품절 아님) — 소스/이미지 안 건드리고 원가만 번장 현재가로 갱신 → eBay 가격 재계산.
/tmp/price_updates.json = [{"id":"cp_...","cost":1000}, ...]

실행:
  docker cp samba-tools/ebay_sourcing/price_sync.py local-samba-api-1:/tmp/price_sync.py
  docker cp price_updates.json local-samba-api-1:/tmp/price_updates.json
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/price_sync.py [account_id]
"""

import asyncio
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.ebay import EbayClient
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlmodel import select

    acc_id = sys.argv[1] if len(sys.argv) > 1 else KV
    updates = json.load(open("/tmp/price_updates.json", encoding="utf-8"))
    tok = current_tenant_id.set(TENANT)
    ok = fail = 0
    # 계정/클라이언트 1회 로드 (세션 무관)
    async with get_write_session() as s0:
        acc = (
            await s0.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == acc_id))
        ).scalars().first()
        addf = acc.additional_fields or {}
    c = EbayClient(
        app_id=addf.get("clientId") or acc.api_key, dev_id=addf.get("devId", ""),
        cert_id=addf.get("clientSecret") or acc.api_secret,
        refresh_token=addf.get("oauthToken") or acc.oauth_refresh_token,
    )
    try:
        for u in updates:
            pid, cost = u["id"], float(u["cost"])
            try:
                offs = await c.get_offers_by_sku(pid)
                if not offs or offs[0].get("status") != "PUBLISHED":
                    print(f"  SKIP {pid} offer {offs[0].get('status') if offs else '없음'}")
                    fail += 1
                    continue
                before = offs[0].get("listing", {}).get("listingId")
                cat = offs[0].get("categoryId", "")
                # 아이템별 세션 (브랜드매핑 충돌 격리)
                async with get_write_session() as s:
                    acc2 = (
                        await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == acc_id))
                    ).scalars().first()
                    p = (
                        await s.execute(select(SambaCollectedProduct).where(SambaCollectedProduct.id == pid))
                    ).scalars().first()
                    p.cost = cost
                    p.sale_price = cost
                    p.original_price = cost
                    s.add(p)
                    await s.flush()
                    res = await dispatch_to_market(
                        s, "ebay", p.model_dump(), category_id=cat, account=acc2,
                        existing_product_no=before,
                    )
                    await s.commit()
                after = (await c.get_offers_by_sku(pid))[0]
                aid = after.get("listing", {}).get("listingId")
                px = after.get("pricingSummary", {}).get("price", {}).get("value")
                flag = "★새리스팅!" if aid != before else "revise0"
                good = res.get("success")
                print(f"  {'OK' if good else 'FAIL'} {pid} 원가{int(cost):,}→${px} [{flag}] {'' if good else res.get('message','')[:40]}")
                ok += 1 if good else 0
                fail += 0 if good else 1
            except Exception as e:
                print(f"  ERR {pid}: {str(e)[:60]}")
                fail += 1
        print(f"\n=== OK={ok} FAIL={fail} / {len(updates)} ===")
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
