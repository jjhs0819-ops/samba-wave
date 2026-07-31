"""리스팅 1인당 구매수량 제한 설정 [컨테이너 실행].

부피 큰 굿즈(응원봉 등)는 한 명이 여러 개 사면 FedEx 요금이 개당 그대로 붙어
배송비를 아무리 받아도 감당이 안 된다. eBay Offer 의 quantityLimitPerBuyer 로 막는다.

updateOffer 는 전체 교체(PUT)라 기존 값을 읽어 합쳐서 보낸다.

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 \
      /tmp/limit_per_buyer.py <SKU> [수량=1]
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
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlmodel import select

    sku = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 1
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
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Content-Language": "en-US",
            }

            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.get(
                    f"{ec._base_url}/sell/inventory/v1/offer?sku={sku}", headers=h
                )
                offers = r.json().get("offers", []) if r.status_code == 200 else []
                if not offers:
                    print(f"Offer 없음 {sku} ({r.status_code})")
                    return
                for o in offers:
                    oid = o["offerId"]
                    payload = {
                        "sku": sku,
                        "marketplaceId": o.get("marketplaceId", "EBAY_US"),
                        "format": o.get("format", "FIXED_PRICE"),
                        "availableQuantity": o.get("availableQuantity", 1),
                        "categoryId": o.get("categoryId"),
                        "listingDescription": o.get("listingDescription"),
                        "listingPolicies": o.get("listingPolicies"),
                        "pricingSummary": o.get("pricingSummary"),
                        "merchantLocationKey": o.get("merchantLocationKey"),
                        # 0 을 주면 필드를 빼서 보낸다 = 한도 해제
                        # (PUT 은 전체 교체라 빠진 필드는 삭제된다)
                        "quantityLimitPerBuyer": limit if limit > 0 else None,
                    }
                    payload = {k: v for k, v in payload.items() if v is not None}
                    ru = await c.put(
                        f"{ec._base_url}/sell/inventory/v1/offer/{oid}",
                        headers=h,
                        json=payload,
                    )
                    print(
                        f"offer={oid} "
                        + (f"1인당 최대 {limit}개" if limit > 0 else "1인당 한도 해제")
                        + f" → {ru.status_code}"
                        + ("" if ru.status_code < 400 else f" {ru.text[:250]}")
                    )
                    if ru.status_code < 400 and o.get("status") == "PUBLISHED":
                        pr = await c.post(
                            f"{ec._base_url}/sell/inventory/v1/offer/{oid}/publish",
                            headers=h,
                        )
                        print(f"  재게시 {pr.status_code}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
