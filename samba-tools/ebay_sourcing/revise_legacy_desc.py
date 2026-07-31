"""레거시(Trading) 리스팅 상세설명 갱신 [컨테이너 실행].

Inventory API 로 만들어지지 않은 옛 리스팅은 /sell/inventory/v1/offer 가 404 라
dispatch_to_market 으로 수정할 수 없다. 이런 건은 Trading ReviseFixedPriceItem 으로
Description 만 직접 바꾼다. (2026-07-23 관세 문구 정정 시 23건이 이 경우였다)

상세설명은 백엔드와 동일 규칙으로 만든다:
  정책이 지정한 템플릿 → top_html 있으면 그 HTML, 없으면 top_image_s3_key 배너 이미지.

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/revise_legacy_desc.py [--dry]
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
DEFAULT_TPL = "dt_01KXD39BCZACRDC1VP23TBP2MS"  # 이베이 기본 상세페이지


def wrap(top_html: str, banner: str) -> str:
    if top_html:
        return top_html
    return (
        '<div style="max-width:900px;margin:0 auto;">'
        f'<img src="{banner}" style="width:100%;display:block;" alt="Store notice">'
        "</div>"
    )


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.resolver import resolve_market_creds
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
            hdr_inv = {"Authorization": f"Bearer {tk}"}
            hdr_tr = {
                "X-EBAY-API-CALL-NAME": "ReviseFixedPriceItem",
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
            ok = fail = skip = 0
            async with httpx.AsyncClient(timeout=60) as c:
                for pid, en, ko, pol_id, nos in rows:
                    lid = (nos or {}).get(KV, "")
                    nm = (en or ko or "")[:40]
                    if not lid:
                        continue
                    # Inventory 로 고칠 수 있는 건은 dispatch 가 담당 — 여기선 건너뛴다
                    r = await c.get(
                        f"{ec._base_url}/sell/inventory/v1/offer?sku={pid}",
                        headers=hdr_inv,
                    )
                    if r.status_code == 200 and r.json().get("offers"):
                        skip += 1
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

                    print(
                        f"{'DRY' if dry else 'RUN'} {nm} | listing {lid} | tpl {tpl_id}"
                    )
                    if dry:
                        continue
                    xml = (
                        '<?xml version="1.0" encoding="utf-8"?>'
                        '<ReviseFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
                        f"<Item><ItemID>{lid}</ItemID>"
                        f"<Description><![CDATA[{desc}]]></Description>"
                        "</Item></ReviseFixedPriceItemRequest>"
                    )
                    rr = await c.post(
                        f"{ec._base_url}/ws/api.dll",
                        content=xml.encode("utf-8"),
                        headers=hdr_tr,
                    )
                    root = ET.fromstring(rr.text)
                    ack = root.findtext(
                        ".//{urn:ebay:apis:eBLBaseComponents}Ack",
                        "",
                    )
                    if ack in ("Success", "Warning"):
                        ok += 1
                        print("   갱신완료")
                    else:
                        fail += 1
                        msg = root.findtext(
                            ".//{urn:ebay:apis:eBLBaseComponents}LongMessage", ""
                        )
                        print(f"   실패: {msg[:110]}")
            print(f"\n완료: 갱신 {ok} / 실패 {fail} / Inventory건 건너뜀 {skip}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
