"""General 캠페인 광고 입찰률 일괄 조정 [컨테이너 실행].

정책(samba_policy.market_policies.eBay.adRate)을 바꿔도 이미 eBay 캠페인에
등록된 광고의 bidPercentage 는 그대로 남는다. 이 스크립트로 맞춘다.
(2026-07-23: 정책은 3% 인데 캠페인에 5% 광고 12건이 남아 있던 건)

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/ad_bid_sync.py [--rate 3.0] [--dry]
"""

import asyncio
import io
import sys
from collections import Counter

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
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlmodel import select

    rate = sys.argv[sys.argv.index("--rate") + 1] if "--rate" in sys.argv else "3.0"
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
            # 광고 API 는 sell.marketing scope 전용 토큰이 필요하다(공용 토큰은 403)
            tk = await ec._get_marketing_token()
            h = {
                "Authorization": f"Bearer {tk}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Content-Language": "en-US",
            }

            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.get(
                    f"{ec._base_url}/sell/marketing/v1/ad_campaign?campaign_status=RUNNING&limit=50",
                    headers=h,
                )
                if r.status_code != 200:
                    print("캠페인 조회 실패", r.status_code, r.text[:200])
                    return
                for cam in r.json().get("campaigns", []):
                    cid = cam.get("campaignId")
                    ads, off = [], 0
                    while True:
                        ra = await c.get(
                            f"{ec._base_url}/sell/marketing/v1/ad_campaign/{cid}/ad"
                            f"?limit=200&offset={off}",
                            headers=h,
                        )
                        if ra.status_code != 200:
                            print("  광고 조회 실패", ra.status_code, ra.text[:150])
                            break
                        page = ra.json().get("ads", [])
                        ads += page
                        if len(page) < 200:
                            break
                        off += 200
                    before = Counter(str(a.get("bidPercentage")) for a in ads)
                    targets = [
                        a for a in ads if str(a.get("bidPercentage")) != str(rate)
                    ]
                    print(
                        f"캠페인 {cid} | 광고 {len(ads)}건 {dict(before)} | 조정대상 {len(targets)}건"
                        + (" [DRY]" if dry else "")
                    )
                    if dry:
                        continue
                    ok = fail = 0
                    for a in targets:
                        # bulk 로 한 번에 보내면 일부 실패 시 원인 추적이 어려워 건별로 처리
                        ru = await c.post(
                            f"{ec._base_url}/sell/marketing/v1/ad_campaign/{cid}"
                            f"/ad/{a['adId']}/update_bid",
                            headers=h,
                            json={"bidPercentage": str(rate)},
                        )
                        if ru.status_code < 400:
                            ok += 1
                        else:
                            fail += 1
                            print(
                                f"  실패 adId={a['adId']} {ru.status_code} {ru.text[:150]}"
                            )
                    print(f"  → {rate}% 로 조정: 성공 {ok} / 실패 {fail}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
