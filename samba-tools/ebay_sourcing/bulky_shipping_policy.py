"""부피 큰 굿즈용 eBay 배송정책 생성 + 해당 리스팅에 적용 [컨테이너 실행].

왜 필요한가 (2026-07-23 사고):
  계정 기본 배송정책이 카드용 "254921241025 ($10 / 추가 $3, Expedited $15 / $3)" 라
  응원봉 같은 부피 상품에도 그대로 붙었다. 페루 3개 주문에서 배송비를 $21 만 받았는데
  실제 FedEx expedited 는 개당 약 $25 (합 $75) — 구조적 적자.

정책 값:
  - Expedited International(FedEx) : 첫 개 $25 + 추가 1개당 $25 (개당 부피가 같아 감액 없음)
  - Standard International         : 동일 $25 / $25 (실측 전까지 보수적으로. 실제 요금 확인되면 낮출 것)
  - 미국행(DOMESTIC 취급)도 동일 기준
  - handling 4일 (기존 정책과 동일)

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/bulky_shipping_policy.py [--apply]
    (--apply 없으면 정책 생성/조회만 하고 리스팅에는 붙이지 않음)
"""

import asyncio
import io
import json
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"  # k-tcg_vault 전용
POLICY_NAME = "굿즈-대형 FedEx $25/$25"
BASE_POLICY = "254921241025"  # 카드 정책 — 배송지역/제외국가를 여기서 그대로 가져온다
GOODS_POLICIES = ("pol_kpopgoods_v1", "pol_01KY2VR2WEDXJTJ20GNB2NMXAN")  # 굿즈 / 앨범

FIRST = "25.0"
ADDL = "25.0"


def body(base: dict) -> dict:
    """기존 카드 정책(base)의 배송지역·제외국가를 그대로 쓰고 요금만 갈아끼운다.

    [중요] 지역을 임의로 "전 세계"로 열면 안 된다. 원래 정책은
    제외국가 57개(Alaska/Hawaii, APO/FPO, 유럽 대부분, 중동, 아프리카 등)가 걸려 있고,
    Standard 는 아시아·호주·브라질·캐나다·중국·유럽·영국·일본·러시아만 간다.
    (2026-07-23: 복제하면서 Worldwide 로 열어버린 것을 원복)
    """
    import copy

    d = copy.deepcopy(base)
    d["name"] = POLICY_NAME
    d.pop("fulfillmentPolicyId", None)
    d.setdefault("globalShipping", False)
    for opt in d.get("shippingOptions", []):
        for svc in opt.get("shippingServices", []):
            svc["shippingCost"] = {"value": FIRST, "currency": "USD"}
            svc["additionalShippingCost"] = {"value": ADDL, "currency": "USD"}
    return d


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.resolver import resolve_market_creds
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlalchemy import text as t
    from sqlmodel import select

    apply = "--apply" in sys.argv
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
            h = {"Authorization": f"Bearer {tk}", "Content-Type": "application/json",
                 "Accept": "application/json", "Content-Language": "en-US"}

            async with httpx.AsyncClient(timeout=60) as c:
                rb = await c.get(
                    f"{ec._base_url}/sell/account/v1/fulfillment_policy/{BASE_POLICY}", headers=h)
                if rb.status_code != 200:
                    print("기준 정책 조회 실패", rb.status_code, rb.text[:200])
                    return
                base = rb.json()
                pol_payload = body(base)

                # 이미 만들어 뒀으면 재사용 (중복 생성 금지)
                r = await c.get(
                    f"{ec._base_url}/sell/account/v1/fulfillment_policy?marketplace_id=EBAY_US",
                    headers=h)
                found = next((p for p in r.json().get("fulfillmentPolicies", [])
                              if p.get("name") == POLICY_NAME), None)
                if found:
                    pid = found["fulfillmentPolicyId"]
                    r = await c.put(
                        f"{ec._base_url}/sell/account/v1/fulfillment_policy/{pid}",
                        headers=h, json=pol_payload)
                    print(f"정책 갱신 {pid} {r.status_code}")
                    if r.status_code >= 400:
                        print(r.text[:400])
                else:
                    r = await c.post(f"{ec._base_url}/sell/account/v1/fulfillment_policy",
                                     headers=h, json=pol_payload)
                    if r.status_code >= 400:
                        print("정책 생성 실패", r.status_code, r.text[:500])
                        return
                    pid = r.json()["fulfillmentPolicyId"]
                    print(f"정책 생성 {pid}")

                if not apply:
                    print("(--apply 없음 → 리스팅 적용 생략)")
                    return

                rows = (await s.execute(t("""
                    SELECT id, name_en FROM samba_collected_product
                    WHERE tenant_id = :tn AND registered_accounts @> CAST(:kv AS jsonb)
                      AND applied_policy_id = ANY(:pols)
                """), {"tn": TENANT, "kv": f'["{KV}"]', "pols": list(GOODS_POLICIES)})).all()
                print(f"적용 대상 {len(rows)}건")
                for sku, nm in rows:
                    ro = await c.get(f"{ec._base_url}/sell/inventory/v1/offer?sku={sku}", headers=h)
                    for o in ro.json().get("offers", []) if ro.status_code == 200 else []:
                        oid = o["offerId"]
                        cur = json.loads(json.dumps(o))  # 원본 그대로 두고 정책만 교체
                        for k in ("offerId", "sku", "marketplaceId", "format", "listing",
                                  "status", "listingDescription"):
                            cur.pop(k, None) if k in ("offerId", "listing", "status") else None
                        payload = {
                            "sku": sku,
                            "marketplaceId": o.get("marketplaceId", "EBAY_US"),
                            "format": o.get("format", "FIXED_PRICE"),
                            "availableQuantity": o.get("availableQuantity", 1),
                            "categoryId": o.get("categoryId"),
                            "listingDescription": o.get("listingDescription"),
                            "listingPolicies": {
                                **(o.get("listingPolicies") or {}),
                                "fulfillmentPolicyId": pid,
                            },
                            "pricingSummary": o.get("pricingSummary"),
                            "merchantLocationKey": o.get("merchantLocationKey"),
                            # [중요] PUT 은 전체 교체다. 안 실어보내면 1인당 구매한도가
                            # 지워진다(2026-07-23 응원봉에서 실제로 날아감).
                            "quantityLimitPerBuyer": o.get("quantityLimitPerBuyer"),
                        }
                        payload = {k: v for k, v in payload.items() if v is not None}
                        ru = await c.put(f"{ec._base_url}/sell/inventory/v1/offer/{oid}",
                                         headers=h, json=payload)
                        print(f"  {nm[:38]} offer={oid} → {ru.status_code}"
                              + ("" if ru.status_code < 400 else f" {ru.text[:200]}"))
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
