"""모든 스마트스토어 계정에서 마스마룰즈 상품 검색."""

import asyncio
from sqlalchemy import select
from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.smartstore import SmartStoreClient


async def search_account(acc) -> None:
    extras = getattr(acc, "additional_fields", None) or {}
    cid = extras.get("clientId", "") or getattr(acc, "api_key", "") or ""
    csec = extras.get("clientSecret", "") or getattr(acc, "api_secret", "") or ""
    if not cid or not csec:
        print(f"  ⚠️ {acc.account_label} 인증정보 없음")
        return

    client = SmartStoreClient(cid, csec)
    print(f"\n=== [{acc.account_label}] 마스마룰즈 검색 ===")

    # smartstore Commerce API: POST /v1/products/search
    # 본문: { searchKeywordType: "SELLER_CODE" or "PRODUCT_NAME", searchKeyword: "마스마룰즈", ... }
    # 페이지 단위로 전체 SALE 상품 가져오기 (작은 검색은 키워드 없이)
    body = {
        "productStatusTypes": ["SALE"],
        "page": 1,
        "size": 100,
        "orderType": "NO",
    }
    try:
        res = await client._call_api("POST", "/v1/products/search", body=body)
        contents = res.get("contents", [])
        total = res.get("totalElements", len(contents))
        print(f"  총 {total}건 (이번 페이지 {len(contents)}건)")
        for it in contents[:50]:
            on = it.get("originProductNo")
            cn = (
                (it.get("channelProducts") or [{}])[0].get("channelProductNo")
                if it.get("channelProducts")
                else None
            )
            name = it.get("name") or it.get("productName") or ""
            status = it.get("statusType") or ""
            print(f"    origin={on} channel={cn} status={status} name={name[:60]}")
    except Exception as e:
        print(f"  ❌ {type(e).__name__}: {str(e)[:200]}")


async def main() -> None:
    async with get_read_session() as session:
        stmt = select(SambaMarketAccount).where(
            SambaMarketAccount.market_type == "smartstore"
        )
        accs = (await session.execute(stmt)).scalars().all()
        for a in accs:
            await search_account(a)


if __name__ == "__main__":
    asyncio.run(main())
