"""eBay 재고 → DB 역동기화 [컨테이너 실행].

재고의 정답은 eBay 다. 판매자가 셀러센터에서 수량을 올리면 그게 진짜다.
DB stock_quantities 는 "판매가능 + 누적판매" 로 맞춰둬야 다음 전송 때
계산이 어긋나지 않는다(eBay 는 취소·환불해도 soldQuantity 를 안 줄인다).

같이 하는 일:
  - 재고가 살아났는데 Offer 가 미게시로 남아 있으면 publish 해서 되살린다
  - 살아난 리스팅 번호를 DB market_product_nos 에 반영한다

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 \
      /tmp/sync_stock_from_ebay.py [--dry]
"""

import asyncio
import io
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"  # k-tcg_vault 전용


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.resolver import resolve_market_creds
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlalchemy import text as t
    from sqlmodel import select

    dry = "--dry" in sys.argv
    tok = current_tenant_id.set(TENANT)
    changed = revived = 0
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
            ax = getattr(acc, "additional_fields", None) or {}
            cr = (
                await resolve_market_creds(
                    s, TENANT, market_type="ebay", store_key="store_ebay"
                )
                or {}
            )
            ec = EbayClient(
                cr.get("clientId")
                or cr.get("appId")
                or ax.get("clientId")
                or ax.get("appId", ""),
                cr.get("devId") or ax.get("devId", ""),
                cr.get("clientSecret")
                or cr.get("certId")
                or ax.get("clientSecret")
                or ax.get("certId", ""),
                cr.get("oauthToken")
                or cr.get("authToken")
                or ax.get("oauthToken")
                or ax.get("authToken", ""),
            )
            tk = await ec._get_access_token()
            h = {
                "Authorization": f"Bearer {tk}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Content-Language": "en-US",
            }

            rows = (
                await s.execute(
                    t("""
                SELECT id FROM samba_collected_product
                WHERE tenant_id = :tn AND registered_accounts @> CAST(:kv AS jsonb)
            """),
                    {"tn": TENANT, "kv": f'["{KV}"]'},
                )
            ).all()
            print(f"대상 {len(rows)}건")

            async with httpx.AsyncClient(timeout=60) as c:
                for (pid,) in rows:
                    r = await c.get(
                        f"{ec._base_url}/sell/inventory/v1/offer?sku={pid}", headers=h
                    )
                    offers = r.json().get("offers", []) if r.status_code == 200 else []
                    if not offers:
                        continue
                    o = offers[0]
                    avail = int(o.get("availableQuantity", 0) or 0)
                    sold = int((o.get("listing") or {}).get("soldQuantity", 0) or 0)
                    total = avail + sold

                    p = (
                        (
                            await s.execute(
                                select(SambaCollectedProduct).where(
                                    SambaCollectedProduct.id == pid
                                )
                            )
                        )
                        .scalars()
                        .first()
                    )
                    nm = (p.name_en or p.name or "")[:38]

                    # 재고 있는데 미게시로 죽어 있으면 되살린다
                    if avail > 0 and o.get("status") != "PUBLISHED":
                        print(f"되살림 {nm} | 재고 {avail} | offer {o['offerId']}")
                        if not dry:
                            pr = await c.post(
                                f"{ec._base_url}/sell/inventory/v1/offer/{o['offerId']}/publish",
                                headers=h,
                            )
                            if pr.status_code in (200, 201):
                                lid = pr.json().get("listingId", "")
                                d = dict(p.market_product_nos or {})
                                d[KV] = lid
                                p.market_product_nos = d
                                revived += 1
                                print(f"   → {lid}")
                            else:
                                print(
                                    f"   publish 실패 {pr.status_code} {pr.text[:90]}"
                                )

                    cur = int((p.stock_quantities or {}).get(KV, 0) or 0)
                    if cur != total:
                        print(
                            f"재고동기화 {nm} | DB {cur} → {total} (가능 {avail} + 판매 {sold})"
                        )
                        changed += 1
                        if not dry:
                            d = dict(p.stock_quantities or {})
                            d[KV] = total
                            p.stock_quantities = d
                            p.sale_status = "in_stock" if avail > 0 else "sold_out"
                    if not dry:
                        s.add(p)
                        await s.commit()
            print(
                f"\n완료: 재고갱신 {changed}건 / 되살림 {revived}건"
                + (" [DRY]" if dry else "")
            )
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
