"""eBay 가 못 가져간 사진 재전송 [컨테이너 실행].

증상: 셀러센터 썸네일이 깨져 보인다.
원인: 정상 리스팅은 사진이 eBay CDN(i.ebayimg.com)으로 옮겨져 있는데, 실패한 건은
      PictureURL 이 우리 도메인(api.samba-wave.co.kr) 그대로다. eBay 가 이미지를
      가져오지 못해 자기 서버에 올리지 못한 상태(2026-07-23 2건 발견).

처리: 해당 SKU 의 inventory_item 에 imageUrls 를 다시 밀어 eBay 가 재수집하게 한다.
      URL 이 같으면 무시될 수 있어 캐시버스터(?v=)를 붙인다.

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 \
      /tmp/fix_missing_photos.py [--dry]
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
NS = "{urn:ebay:apis:eBLBaseComponents}"


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.resolver import resolve_market_creds
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlalchemy import text as t
    from sqlmodel import select

    dry = "--dry" in sys.argv
    tok = current_tenant_id.set(TENANT)
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
            hi = {
                "Authorization": f"Bearer {tk}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Content-Language": "en-US",
            }
            ht = {
                "X-EBAY-API-CALL-NAME": "GetItem",
                "X-EBAY-API-SITEID": "0",
                "X-EBAY-API-COMPATIBILITY-LEVEL": "1349",
                "X-EBAY-API-IAF-TOKEN": tk,
                "Content-Type": "text/xml",
            }

            rows = (
                await s.execute(
                    t("""
                SELECT id, name_en, name, images, market_product_nos
                FROM samba_collected_product
                WHERE tenant_id = :tn AND registered_accounts @> CAST(:kv AS jsonb)
            """),
                    {"tn": TENANT, "kv": f'["{KV}"]'},
                )
            ).all()

            bad, ok, fail = [], 0, 0
            async with httpx.AsyncClient(timeout=60) as c:
                for pid, en, ko, imgs, nos in rows:
                    lid = (nos or {}).get(KV, "")
                    if not lid:
                        continue
                    xml = (
                        '<?xml version="1.0" encoding="utf-8"?>'
                        '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
                        f"<ItemID>{lid}</ItemID><DetailLevel>ReturnAll</DetailLevel></GetItemRequest>"
                    )
                    r = await c.post(
                        f"{ec._base_url}/ws/api.dll", content=xml, headers=ht
                    )
                    pics = [
                        x.text or ""
                        for x in ET.fromstring(r.text).findall(
                            f".//{NS}Item/{NS}PictureDetails/{NS}PictureURL"
                        )
                    ]
                    # eBay CDN 으로 안 옮겨진 것 = 수집 실패
                    if pics and not any("ebayimg.com" in p for p in pics):
                        bad.append((pid, (en or ko or "")[:40], imgs or []))

                print(f"사진 미수집 {len(bad)}건")
                for pid, nm, imgs in bad:
                    print(f"{'DRY' if dry else 'RUN'} {nm}")
                    if dry or not imgs:
                        continue
                    ri = await c.get(
                        f"{ec._base_url}/sell/inventory/v1/inventory_item/{pid}",
                        headers=hi,
                    )
                    if ri.status_code != 200:
                        fail += 1
                        print(f"   item 조회 실패 {ri.status_code}")
                        continue
                    item = ri.json()
                    item.pop("sku", None)
                    # 같은 URL 이면 eBay 가 변경 없음으로 넘길 수 있어 쿼리스트링을 붙인다
                    item.setdefault("product", {})["imageUrls"] = [
                        (u + ("&" if "?" in u else "?") + "r=1") for u in imgs
                    ]
                    ru = await c.put(
                        f"{ec._base_url}/sell/inventory/v1/inventory_item/{pid}",
                        headers=hi,
                        json=item,
                    )
                    if ru.status_code < 400:
                        ok += 1
                        print("   이미지 재전송 완료")
                    else:
                        fail += 1
                        print(f"   실패 {ru.status_code} {ru.text[:150]}")
            print(f"\n완료: 재전송 {ok} / 실패 {fail}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
