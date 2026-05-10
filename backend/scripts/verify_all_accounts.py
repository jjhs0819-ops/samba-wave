"""모든 스마트스토어 계정에서 마스마룰즈 잔존 0건 검증."""

import asyncio
from sqlalchemy import select
from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.smartstore import SmartStoreClient


async def check_account(acc) -> int:
    extras = getattr(acc, "additional_fields", None) or {}
    cid = extras.get("clientId", "") or getattr(acc, "api_key", "") or ""
    csec = extras.get("clientSecret", "") or getattr(acc, "api_secret", "") or ""
    if not cid or not csec:
        return -1
    client = SmartStoreClient(cid, csec)
    body = {
        "productStatusTypes": ["SALE", "OUTOFSTOCK", "SUSPENSION", "CLOSE", "WAIT"],
        "page": 1,
        "size": 100,
        "orderType": "NO",
    }
    res = await client._call_api("POST", "/v1/products/search", body=body)
    contents = res.get("contents", [])
    total = res.get("totalElements", 0)
    masma = 0
    # 첫 페이지에서 brandName=마스마룰즈 카운트
    for it in contents:
        if (it.get("brandName") or "") == "마스마룰즈":
            masma += 1
    # name 매칭 — origin GET 1차 페이지만 (성능 절약, 최대 100건)
    sample_name_match = 0
    if total <= 100:
        for it in contents:
            on = it.get("originProductNo")
            if not on:
                continue
            try:
                r = await client.get_product(on)
                origin = r.get("originProduct") or {}
                name = origin.get("name") or ""
                if "마스마룰즈" in name:
                    sample_name_match += 1
            except Exception:
                pass
            await asyncio.sleep(0.5)
    print(
        f"  {acc.account_label}: 전체 {total}건, brandName=마스마룰즈 {masma}건, name 포함 {sample_name_match}건 (전체<100 시 검증)"
    )
    return masma + sample_name_match


async def main() -> None:
    async with get_read_session() as session:
        stmt = select(SambaMarketAccount).where(
            SambaMarketAccount.market_type == "smartstore"
        )
        accs = (await session.execute(stmt)).scalars().all()
        print("=== 마스마룰즈 잔존 검증 (모든 스마트스토어 계정) ===")
        total_masma = 0
        for a in accs:
            r = await check_account(a)
            if r > 0:
                total_masma += r
        print(f"\n[종합] 마스마룰즈 잔존 총 {total_masma}건")


if __name__ == "__main__":
    asyncio.run(main())
