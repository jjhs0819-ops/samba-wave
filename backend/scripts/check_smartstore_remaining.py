"""스마트스토어 모든 계정 + 마스마룰즈 잔존 직접 조회."""

import asyncio
from sqlalchemy import select
from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.smartstore import SmartStoreClient


async def list_account_products(acc):
    extras = getattr(acc, "additional_fields", None) or {}
    cid = extras.get("clientId", "") or getattr(acc, "api_key", "") or ""
    csec = extras.get("clientSecret", "") or getattr(acc, "api_secret", "") or ""
    if not cid or not csec:
        print(f"  ⚠️ {acc.account_label} 인증정보 없음")
        return
    client = SmartStoreClient(cid, csec)
    try:
        # 검색 — 전체 상품 (대용량 페이지)
        # SmartStoreClient에 search/list 메서드가 있는지 확인
        page = 1
        size = 100
        all_items: list[dict] = []
        while page < 20:
            res = (
                await client.search_products(
                    searchType="ALL",
                    productStatusTypes="SALE,WAIT,SUSPENSION,CLOSE",
                    page=page,
                    size=size,
                )
                if hasattr(client, "search_products")
                else None
            )
            if res is None:
                break
            items = res.get("contents") or res.get("products") or []
            all_items.extend(items)
            if len(items) < size:
                break
            page += 1
        masma = [
            it
            for it in all_items
            if "마스마룰즈" in (it.get("name") or it.get("productName") or "")
            or "MASMARULEZ" in (it.get("name") or it.get("productName") or "").upper()
        ]
        print(
            f"  {acc.account_label}: 전체 {len(all_items)}건, 마스마룰즈 {len(masma)}건"
        )
        for it in masma[:10]:
            print(
                f"    no={it.get('originProductNo') or it.get('productNo')} name={(it.get('name') or it.get('productName') or '')[:40]} status={it.get('statusType') or it.get('status')}"
            )
    except Exception as e:
        print(f"  ❌ {acc.account_label} 오류: {type(e).__name__}: {e}")


async def main() -> None:
    async with get_read_session() as session:
        stmt = select(SambaMarketAccount).where(
            SambaMarketAccount.market_type == "smartstore"
        )
        accs = (await session.execute(stmt)).scalars().all()
        print(f"스마트스토어 계정 {len(accs)}개")
        for a in accs:
            print(f"  - id={a.id} label={a.account_label} seller={a.seller_id}")

        print("\n=== 각 계정별 마스마룰즈 상품 조회 ===")
        for a in accs:
            await list_account_products(a)


if __name__ == "__main__":
    asyncio.run(main())
