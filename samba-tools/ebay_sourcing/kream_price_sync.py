"""KREAM 소싱 eBay 리스팅 가격 동기화 [컨테이너 실행].

KREAM은 재고 안 죽지만 시세(즉시구매가)가 변동 → 공식 API로 최신가 재조회 →
원가 변동 시 정책 재계산 → revise(수수료0). KREAM 품절/삭제면 판매중지.
KV(k-tcg_vault) 전용. 이미지·매칭 불필요라 안전 자동화.

실행:
  docker cp samba-tools/ebay_sourcing/kream_price_sync.py local-samba-api-1:/tmp/kream_price_sync.py
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/kream_price_sync.py [--min-delta 1000] [--dry]
"""

import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TEN = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"


def _opt(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


async def main():
    import backend.main  # noqa
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.resolver import resolve_market_creds
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.ebay import EbayClient
    from backend.domain.samba.proxy.kream import KreamPartnerClient
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlalchemy import text as t
    from sqlmodel import select

    min_delta = float(_opt("--min-delta", "1000"))
    dry = "--dry" in sys.argv
    price_key = "lowest_95_price"

    tok = current_tenant_id.set(TEN)
    try:
        async with get_write_session() as s:
            kacc = (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.market_type == "kream"))).scalars().first()
            kext = kacc.additional_fields if isinstance(kacc.additional_fields, dict) else {}
            kcli = KreamPartnerClient(str(kext.get("apiService") or ""), str(kext.get("apiKey") or kacc.api_key or ""), str(kext.get("apiSecret") or kacc.api_secret or ""))

            acc = (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()
            aext = getattr(acc, "additional_fields", None) or {}
            cr = await resolve_market_creds(s, TEN, market_type="ebay", store_key="store_ebay") or {}
            ecli = EbayClient(cr.get("clientId") or cr.get("appId") or aext.get("clientId") or aext.get("appId", ""), cr.get("devId") or aext.get("devId", ""), cr.get("clientSecret") or cr.get("certId") or aext.get("clientSecret") or aext.get("certId", ""), cr.get("oauthToken") or cr.get("authToken") or aext.get("oauthToken") or aext.get("authToken", ""))

            rows = (await s.execute(
                select(SambaCollectedProduct).where(
                    SambaCollectedProduct.source_site == "KREAM",
                    SambaCollectedProduct.registered_accounts.isnot(None),
                )
            )).scalars().all()
            targets = [p for p in rows if KV in (p.registered_accounts or [])]
            print(f"KREAM 등록분: {len(targets)}")

            for p in targets:
                lid = (p.market_product_nos or {}).get(KV)
                if not lid:
                    continue
                code, body = await kcli.get_product(int(p.site_product_id))
                if code != 200:
                    print(f"  {p.name_en[:35]} | KREAM조회실패 {code} skip")
                    continue
                opts = body.get("options") or [{}]
                new_cost = None
                for o in opts:
                    new_cost = o.get(price_key) or o.get("lowest_normal_price") or o.get("lowest_100_price")
                    if new_cost:
                        break
                old_cost = float(p.cost or 0)
                if not new_cost:
                    print(f"  {p.name_en[:35]} | KREAM 품절/무가격 → 판매중지 필요(수동확인)")
                    continue
                new_cost = float(new_cost)
                delta = new_cost - old_cost
                if abs(delta) < min_delta:
                    print(f"  {p.name_en[:35]} | 변동없음 (₩{int(old_cost):,})")
                    continue
                # 기존 offer 카테고리 유지
                offr = await ecli._call("GET", "/sell/inventory/v1/offer", params={"sku": p.id})
                cat = ""
                for o in offr.get("offers", []):
                    cat = o.get("categoryId") or ""
                    if cat:
                        break
                print(f"  {p.name_en[:35]} | ₩{int(old_cost):,} → ₩{int(new_cost):,} ({'+' if delta>0 else ''}{int(delta):,}) cat={cat}{' [DRY]' if dry else ''}")
                if dry:
                    continue
                p.cost = new_cost
                p.sale_price = new_cost
                p.original_price = new_cost
                s.add(p)
                await s.flush()
                res = await dispatch_to_market(s, "ebay", p.model_dump(), category_id=cat or "108857", account=acc, existing_product_no=str(lid))
                print(f"      revise: {res.get('success')}")
            if not dry:
                await s.commit()
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
