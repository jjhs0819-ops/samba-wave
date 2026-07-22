"""PSA 등급카드 후처리 [컨테이너 실행].

register 직후 실행. transform 기본값이 등급카드/일본판에 안 맞아서 직접 교정한다.
  - condition: Ungraded(4000) → Graded(2750) = Inventory API enum "LIKE_NEW"
  - conditionDescriptors: 27501=Professional Grader(275010=PSA), 27502=Grade(275020=10)
    ※ 27503(Certification Number)은 값 검증 불가로 미사용 — 넣으면 NULL 오류
  - 일본판이면 aspects Language=Japanese, 원산지=Japan (transform 기본이 Korean 고정)

라이브 실측 검증(2026-07-22): 위 조합 적용 시 리스팅에 "평가됨 - PSA 10: 전문 등급 있음" 표기됨.

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/graded_fix.py <SKU> [--jp] [--grade 10]
"""

import asyncio
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
GRADE_VALUE = {"10": "275020"}  # 실측 확인된 값만 사용


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.resolver import resolve_market_creds
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlmodel import select

    sku = sys.argv[1]
    is_jp = "--jp" in sys.argv
    grade = sys.argv[sys.argv.index("--grade") + 1] if "--grade" in sys.argv else "10"

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            acc = (
                await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV))
            ).scalars().first()
            ax = getattr(acc, "additional_fields", None) or {}
            cr = await resolve_market_creds(s, TENANT, market_type="ebay", store_key="store_ebay") or {}
            ec = EbayClient(
                cr.get("clientId") or cr.get("appId") or ax.get("clientId") or ax.get("appId", ""),
                cr.get("devId") or ax.get("devId", ""),
                cr.get("clientSecret") or cr.get("certId") or ax.get("clientSecret") or ax.get("certId", ""),
                cr.get("oauthToken") or cr.get("authToken") or ax.get("oauthToken") or ax.get("authToken", ""),
            )
            inv = await ec._call("GET", f"/sell/inventory/v1/inventory_item/{sku}")
            inv.pop("sku", None)
            inv.pop("locale", None)
            inv["condition"] = "LIKE_NEW"  # = Graded(2750)
            inv["conditionDescriptors"] = [
                {"name": "27501", "values": ["275010"]},  # Professional Grader = PSA
                {"name": "27502", "values": [GRADE_VALUE.get(grade, "275020")]},
            ]
            if is_jp:
                asp = inv.setdefault("product", {}).setdefault("aspects", {})
                asp["Language"] = ["Japanese"]
                asp["Country/Region of Manufacture"] = ["Japan"]
            await ec._call("PUT", f"/sell/inventory/v1/inventory_item/{sku}", body=inv)
            print(f"OK {sku} → Graded PSA {grade}" + (" / Japanese" if is_jp else ""))
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
