"""배송정책 제외국가 일괄 추가 [컨테이너 실행].

남미는 통관 지연·관세 분쟁·분실이 잦아 브라질·콜롬비아만 남기고 막는다.
페루(PE)는 진행 중인 거래가 있어 당분간 열어둔다(2026-07-23 결정).
멕시코(MX)는 북미라 원래 남미 목록에 없다.

eBay 는 "지역 제외 후 그 안의 특정 국가만 다시 허용" 이 안 되므로
국가 코드를 하나씩 regionExcluded 에 넣는다.

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/block_regions.py [--dry]
"""

import asyncio
import io
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"  # k-tcg_vault 전용

POLICIES = ["254921241025", "255030960025"]  # 카드 / 굿즈-대형
# 남미 전체에서 BR·CO·PE 를 뺀 목록
BLOCK = ["AR", "BO", "CL", "EC", "FK", "GF", "GY", "PY", "SR", "UY", "VE"]


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.resolver import resolve_market_creds
    from backend.domain.samba.proxy.ebay import EbayClient
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
            h = {
                "Authorization": f"Bearer {tk}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Content-Language": "en-US",
            }

            async with httpx.AsyncClient(timeout=60) as c:
                for pid in POLICIES:
                    r = await c.get(
                        f"{ec._base_url}/sell/account/v1/fulfillment_policy/{pid}",
                        headers=h,
                    )
                    if r.status_code != 200:
                        print(f"{pid} 조회 실패 {r.status_code} {r.text[:150]}")
                        continue
                    d = r.json()
                    stl = d.setdefault("shipToLocations", {})
                    exc = stl.setdefault("regionExcluded", [])
                    have = {x.get("regionName") for x in exc}
                    add = [x for x in BLOCK if x not in have]
                    exc.extend({"regionName": x} for x in add)
                    print(
                        f"{pid} {d.get('name')} | 기존 제외 {len(have)}개 → 추가 {len(add)}개 {add}"
                        + (" [DRY]" if dry else "")
                    )
                    if dry or not add:
                        continue
                    d.pop("fulfillmentPolicyId", None)
                    d.setdefault("globalShipping", False)
                    ru = await c.put(
                        f"{ec._base_url}/sell/account/v1/fulfillment_policy/{pid}",
                        headers=h,
                        json=d,
                    )
                    print(
                        f"  → {ru.status_code}"
                        + ("" if ru.status_code < 400 else f" {ru.text[:250]}")
                    )
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
