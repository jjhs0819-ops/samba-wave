"""eBay 라이브/비활성 ↔ DB 매칭 정리 [컨테이너 실행].

무엇을 보나:
  1. ActiveList  — 라이브 리스팅. DB market_product_nos 와 번호가 맞는지
  2. UnsoldList  — 종료된 리스팅. DB 는 아직 등록됨으로 알고 있는지
  3. 미게시 Offer — 재고>0 인데 publish 안 된 고아 Offer (2026-07-23 사고 잔해)

--fix 를 주면:
  - DB 번호가 옛 번호면 라이브 번호로 갱신
  - 종료된 리스팅인데 재고>0 이고 미게시 Offer 가 있으면 publish 로 복구
  - 종료됐고 살릴 수 없으면 registered_accounts 에서 제거해 "미등록"으로 되돌림

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/reconcile.py [--fix]
"""

import asyncio
import io
import sys
import xml.etree.ElementTree as ET

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"  # k-tcg_vault 전용
NS = {"e": "urn:ebay:apis:eBLBaseComponents"}


def _tok(x: str) -> set:
    """제목 비교용 토큰. 중복 리스팅 판정에 쓴다."""
    import re

    stop = {"pokemon", "card", "korean", "korea", "tcg", "new", "sealed", "the", "of"}
    return set(re.findall(r"[a-z0-9]+", (x or "").lower())) - stop


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

    fix = "--fix" in sys.argv
    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            acc = (await s.execute(
                select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()
            ax = getattr(acc, "additional_fields", None) or {}
            cr = await resolve_market_creds(s, TENANT, market_type="ebay", store_key="store_ebay") or {}
            ec = EbayClient(
                cr.get("clientId") or cr.get("appId") or ax.get("clientId") or ax.get("appId", ""),
                cr.get("devId") or ax.get("devId", ""),
                cr.get("clientSecret") or cr.get("certId") or ax.get("clientSecret") or ax.get("certId", ""),
                cr.get("oauthToken") or cr.get("authToken") or ax.get("oauthToken") or ax.get("authToken", ""))
            tk = await ec._get_access_token()
            hdr = {"X-EBAY-API-CALL-NAME": "GetMyeBaySelling", "X-EBAY-API-SITEID": "0",
                   "X-EBAY-API-COMPATIBILITY-LEVEL": "1349", "X-EBAY-API-IAF-TOKEN": tk,
                   "Content-Type": "text/xml"}

            async def lst(name):
                xml = ('<?xml version="1.0" encoding="utf-8"?>'
                       '<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
                       f"<{name}><Include>true</Include><Pagination><EntriesPerPage>200</EntriesPerPage>"
                       f"<PageNumber>1</PageNumber></Pagination></{name}></GetMyeBaySellingRequest>")
                async with httpx.AsyncClient(timeout=60) as c:
                    r = await c.post(f"{ec._base_url}/ws/api.dll", content=xml, headers=hdr)
                return {i.findtext("e:ItemID", "", NS): i.findtext("e:Title", "", NS)
                        for i in ET.fromstring(r.text).findall(f".//e:{name}/e:ItemArray/e:Item", NS)}

            active = await lst("ActiveList")
            unsold = await lst("UnsoldList")
            print(f"라이브 {len(active)} / 종료 {len(unsold)}")

            rows = (await s.execute(t("""
                SELECT id, name_en, name, market_product_nos, stock_quantities, sale_status
                FROM samba_collected_product
                WHERE tenant_id = :tn AND registered_accounts @> CAST(:kv AS jsonb)
            """), {"tn": TENANT, "kv": f'["{KV}"]'})).all()
            print(f"DB 등록됨 {len(rows)}")

            h = {"Authorization": f"Bearer {tk}"}
            ok = stale = revived = orphan = 0
            async with httpx.AsyncClient(timeout=60) as c:
                for pid, en, ko, nos, qty, ss in rows:
                    no = (nos or {}).get(KV, "")
                    nm = (en or ko or "")[:36]
                    if no and no in active:
                        ok += 1
                        continue

                    # 라이브에 없다 → SKU 기준으로 실제 상태 확인
                    r = await c.get(f"{ec._base_url}/sell/inventory/v1/offer?sku={pid}", headers=h)
                    offers = r.json().get("offers", []) if r.status_code == 200 else []
                    pub = next((o for o in offers if o.get("status") == "PUBLISHED"), None)
                    if pub:
                        lid = (pub.get("listing") or {}).get("listingId", "")
                        stale += 1
                        print(f"번호불일치 {nm} DB={no or '-'} → 실제={lid}")
                        if fix and lid:
                            p = (await s.execute(select(SambaCollectedProduct).where(
                                SambaCollectedProduct.id == pid))).scalars().first()
                            d = dict(p.market_product_nos or {})
                            d[KV] = lid
                            p.market_product_nos = d
                            s.add(p)
                            await s.commit()
                        continue

                    unp = next((o for o in offers if o.get("status") != "PUBLISHED"), None)
                    have_qty = int((qty or {}).get(KV, 0) or 0)
                    if unp and have_qty > 0:
                        orphan += 1
                        # [중요] 같은 상품이 다른 SKU 로 이미 라이브면 publish 시 중복 리스팅 →
                        # eBay 제재 대상. 제목이 겹치면 복구하지 않는다.
                        title_key = _tok(en or ko or "")
                        dup = any(
                            title_key and _tok(x) and
                            len(title_key & _tok(x)) / len(title_key | _tok(x)) >= 0.6
                            for x in active.values()
                        )
                        if dup:
                            print(f"미게시(중복이라 복구안함) {nm} offer={unp.get('offerId')}")
                            continue
                        print(f"미게시(복구가능) {nm} offer={unp.get('offerId')}")
                        if fix:
                            pr = await c.post(
                                f"{ec._base_url}/sell/inventory/v1/offer/{unp['offerId']}/publish",
                                headers={**h, "Content-Type": "application/json"})
                            if pr.status_code in (200, 201):
                                lid = pr.json().get("listingId", "")
                                p = (await s.execute(select(SambaCollectedProduct).where(
                                    SambaCollectedProduct.id == pid))).scalars().first()
                                d = dict(p.market_product_nos or {})
                                d[KV] = lid
                                p.market_product_nos = d
                                s.add(p)
                                await s.commit()
                                revived += 1
                                print(f"   복구 → {lid}")
                            else:
                                print(f"   publish 실패 {pr.status_code} {pr.text[:90]}")
                        continue

                    # 살릴 수 없음 → DB 를 미등록으로 되돌려 재등록 대상이 되게 한다
                    print(f"종료됨(복구불가) {nm} DB={no or '-'} 재고={have_qty} {ss}")
                    if fix:
                        p = (await s.execute(select(SambaCollectedProduct).where(
                            SambaCollectedProduct.id == pid))).scalars().first()
                        p.registered_accounts = [a for a in (p.registered_accounts or []) if a != KV]
                        d = dict(p.market_product_nos or {})
                        d.pop(KV, None)
                        p.market_product_nos = d
                        s.add(p)
                        await s.commit()

            print(f"\n정상 {ok} / 번호불일치 {stale} / 미게시복구대상 {orphan} / 복구완료 {revived}")
            db_nos = {(n or {}).get(KV, "") for _, _, _, n, _, _ in rows}
            ghost = [(i, ti) for i, ti in active.items() if i not in db_nos]
            print(f"DB에 없는 라이브 리스팅 {len(ghost)}")
            for i, ti in ghost[:20]:
                print(f"  {i} {ti[:46]}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
