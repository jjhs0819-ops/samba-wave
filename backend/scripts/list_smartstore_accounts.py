"""모든 스마트스토어 계정 + 그 계정에 한 상품번호 GET 시도."""

import asyncio
from sqlalchemy import select
from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.smartstore import SmartStoreClient


async def main() -> None:
    async with get_read_session() as session:
        stmt = select(SambaMarketAccount).where(
            SambaMarketAccount.market_type == "smartstore"
        )
        accs = (await session.execute(stmt)).scalars().all()
        print(f"스마트스토어 계정 {len(accs)}개\n")
        for a in accs:
            extras = getattr(a, "additional_fields", None) or {}
            cid = extras.get("clientId", "") or getattr(a, "api_key", "") or ""
            csec = extras.get("clientSecret", "") or getattr(a, "api_secret", "") or ""
            print(f"  id={a.id}")
            print(f"  account_label={a.account_label}")
            print(f"  seller_id={a.seller_id}")
            print(f"  market_name={a.market_name}")
            print(f"  clientId={cid[:8] + '***' if cid else 'None'}")
            print(f"  has_secret={bool(csec)}")
            print()

        # 화면의 한 상품 ID로 GET 시도 — 어느 계정 소유인지 식별
        target_no = "13511265761"
        print(f"=== 상품번호 {target_no} 소유자 식별 ===")
        for a in accs:
            extras = getattr(a, "additional_fields", None) or {}
            cid = extras.get("clientId", "") or getattr(a, "api_key", "") or ""
            csec = extras.get("clientSecret", "") or getattr(a, "api_secret", "") or ""
            if not cid or not csec:
                continue
            client = SmartStoreClient(cid, csec)
            try:
                r = await client.get_product(target_no)
                origin = r.get("originProduct") or {}
                print(f"  ✅ {a.account_label}: GET 성공")
                print(f"     name={(origin.get('name') or '')[:60]}")
                print(f"     statusType={origin.get('statusType')}")
                print(f"     stockQuantity={origin.get('stockQuantity')}")
            except Exception as e:
                msg = str(e)[:120]
                print(f"  ❌ {a.account_label}: {type(e).__name__}: {msg}")


if __name__ == "__main__":
    asyncio.run(main())
