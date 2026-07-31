"""DB id ≠ eBay SKU 인 리스팅의 상세설명 갱신 + 실제 SKU 기록 [컨테이너 실행].

일부 리스팅은 SKU 가 우리 상품 id(cp_...)가 아니라 카드 품번(SV2A-177-165 등)으로
등록돼 있다. 이러면 dispatch_to_market 이 offer 를 못 찾아(404) 수정이 전부 실패한다.
Trading GetItem 으로 실제 SKU 를 알아내 Inventory 로 수정하고, 알아낸 SKU 를
extra_data['ebay_sku'] 에 남겨 다음부터 추적 가능하게 한다.

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/fix_sku_mismatch.py [--dry]
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
DEFAULT_TPL = "dt_01KXD39BCZACRDC1VP23TBP2MS"
NS = "{urn:ebay:apis:eBLBaseComponents}"


def wrap(top_html: str, banner: str) -> str:
    if top_html:
        return top_html
    return (
        '<div style="max-width:900px;margin:0 auto;">'
        f'<img src="{banner}" style="width:100%;display:block;" alt="Store notice"></div>'
    )


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.resolver import resolve_market_creds
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.policy.repository import SambaPolicyRepository
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
                SELECT id, name_en, name, applied_policy_id, market_product_nos
                FROM samba_collected_product
                WHERE tenant_id = :tn AND registered_accounts @> CAST(:kv AS jsonb)
            """),
                    {"tn": TENANT, "kv": f'["{KV}"]'},
                )
            ).all()

            tpl_cache: dict[str, tuple[str, str]] = {}
            ok = fail = 0
            async with httpx.AsyncClient(timeout=60) as c:
                for pid, en, ko, pol_id, nos in rows:
                    lid = (nos or {}).get(KV, "")
                    nm = (en or ko or "")[:38]
                    if not lid:
                        continue
                    r = await c.get(
                        f"{ec._base_url}/sell/inventory/v1/offer?sku={pid}", headers=hi
                    )
                    if r.status_code == 200 and r.json().get("offers"):
                        continue  # id 로 찾히는 정상 건

                    xml = (
                        '<?xml version="1.0" encoding="utf-8"?>'
                        '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
                        f"<ItemID>{lid}</ItemID><DetailLevel>ReturnAll</DetailLevel></GetItemRequest>"
                    )
                    rt = await c.post(
                        f"{ec._base_url}/ws/api.dll", content=xml, headers=ht
                    )
                    real = (
                        ET.fromstring(rt.text).findtext(f".//{NS}Item/{NS}SKU", "")
                        or ""
                    )
                    if not real or real == pid:
                        print(
                            f"SKIP {nm} | listing {lid} | 실제SKU '{real}' (Trading 전용 추정)"
                        )
                        continue

                    ro = await c.get(
                        f"{ec._base_url}/sell/inventory/v1/offer?sku={real}", headers=hi
                    )
                    offers = (
                        ro.json().get("offers", []) if ro.status_code == 200 else []
                    )
                    if not offers:
                        print(
                            f"SKIP {nm} | 실제SKU {real} 로도 offer 없음 ({ro.status_code})"
                        )
                        continue

                    tpl_id = DEFAULT_TPL
                    if pol_id:
                        pol = await SambaPolicyRepository(s).get_async(pol_id)
                        _ext = (getattr(pol, "extras", None) or {}) if pol else {}
                        tpl_id = (
                            (_ext.get("market_detail_templates") or {}).get("eBay")
                            or _ext.get("detail_template_id")
                            or DEFAULT_TPL
                        )
                    if tpl_id not in tpl_cache:
                        row = (
                            await s.execute(
                                t(
                                    "SELECT top_html, top_image_s3_key FROM samba_detail_template WHERE id=:i"
                                ),
                                {"i": tpl_id},
                            )
                        ).first()
                        tpl_cache[tpl_id] = (
                            (row[0] or "", row[1] or "") if row else ("", "")
                        )
                    desc = wrap(*tpl_cache[tpl_id])

                    print(f"{'DRY' if dry else 'RUN'} {nm} | id={pid} → SKU={real}")
                    if dry:
                        continue
                    for o in offers:
                        payload = {
                            "sku": real,
                            "marketplaceId": o.get("marketplaceId", "EBAY_US"),
                            "format": o.get("format", "FIXED_PRICE"),
                            "availableQuantity": o.get("availableQuantity", 1),
                            "categoryId": o.get("categoryId"),
                            "listingDescription": desc,
                            "listingPolicies": o.get("listingPolicies"),
                            "pricingSummary": o.get("pricingSummary"),
                            "merchantLocationKey": o.get("merchantLocationKey"),
                            "quantityLimitPerBuyer": o.get("quantityLimitPerBuyer"),
                        }
                        payload = {k: v for k, v in payload.items() if v is not None}
                        ru = await c.put(
                            f"{ec._base_url}/sell/inventory/v1/offer/{o['offerId']}",
                            headers=hi,
                            json=payload,
                        )
                        if ru.status_code < 400:
                            ok += 1
                            print("   갱신완료")
                        else:
                            fail += 1
                            print(f"   실패 {ru.status_code} {ru.text[:150]}")
                    # 다음부터 추적 가능하도록 실제 SKU 를 남긴다
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
                    ed = dict(p.extra_data or {})
                    ed["ebay_sku"] = real
                    p.extra_data = ed
                    s.add(p)
                    await s.commit()
            print(f"\n완료: 갱신 {ok} / 실패 {fail}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
