"""화면의 채널상품번호 13511265761 의 origin / 소유 계정 식별."""

import asyncio
from sqlalchemy import select
from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.smartstore import SmartStoreClient


CHANNEL_NOS = [
    "13511265761",
    "13511264783",
    "13511263232",
    "13511214362",
    "13511206039",
]


async def main() -> None:
    async with get_read_session() as session:
        stmt = select(SambaMarketAccount).where(
            SambaMarketAccount.market_type == "smartstore"
        )
        accs = (await session.execute(stmt)).scalars().all()

        for cn in CHANNEL_NOS:
            print(f"\n=== 채널상품번호 {cn} ===")
            for a in accs:
                extras = getattr(a, "additional_fields", None) or {}
                cid = extras.get("clientId", "") or getattr(a, "api_key", "") or ""
                csec = (
                    extras.get("clientSecret", "") or getattr(a, "api_secret", "") or ""
                )
                if not cid or not csec:
                    continue
                client = SmartStoreClient(cid, csec)
                # 채널 GET
                try:
                    r = await client._call_api(
                        "GET", f"/v2/products/channel-products/{cn}"
                    )
                    origin = r.get("originProduct") or {}
                    print(f"  ✅ {a.account_label}: 발견")
                    print(f"     name={(origin.get('name') or '')[:60]}")
                    print(f"     statusType={origin.get('statusType')}")
                    print(
                        f"     originProductNo={r.get('originProductNo') or origin.get('originProductNo')}"
                    )
                    break
                except Exception as e:
                    msg = str(e)[:60]
                    if "404" in msg:
                        continue
                    print(f"  ❌ {a.account_label}: {type(e).__name__}: {msg}")
            else:
                print("  → 4개 계정 모두 미발견")


if __name__ == "__main__":
    asyncio.run(main())
