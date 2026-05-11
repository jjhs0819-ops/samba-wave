"""1377156 등록된 스마트스토어 상품 GET → 전체 응답에서 addItems 위치 탐색."""

import asyncio
import json
from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.smartstore import SmartStoreClient


async def main() -> None:
    async with get_read_session() as session:
        acc = await session.get(SambaMarketAccount, "ma_01KM2K57Z8BQY984WC4HE93VQJ")
    extras = getattr(acc, "additional_fields", None) or {}
    client = SmartStoreClient(extras.get("clientId"), extras.get("clientSecret"))
    r = await client.get_product("13453384641")
    s = json.dumps(r, ensure_ascii=False)
    # productAddItems 위치 모두 찾기
    pos = 0
    while True:
        i = s.find("productAddItem", pos)
        if i == -1:
            break
        print(f"  productAddItems @ idx={i}: {s[max(0, i - 50) : i + 200]}")
        pos = i + 10
    # 옵션 관련 모든 키
    print("\n[r 최상위 키]")
    print(list(r.keys()))
    print("\n[originProduct 최상위 키]")
    o = r.get("originProduct") or {}
    print(list(o.keys()))
    print("\n[detailAttribute 키]")
    print(list((o.get("detailAttribute") or {}).keys()))
    print("\n[smartstoreChannelProduct 키]")
    sc = r.get("smartstoreChannelProduct") or {}
    print(list(sc.keys()))
    # addItems / additional 검색
    for k in ["productAddItems", "additionalProducts", "supplementaryProducts"]:
        for src in (o, o.get("detailAttribute") or {}, sc):
            if k in src:
                print(
                    f"\n  ✅ {k} 발견 in {list(src.keys())[:3]}…  값: {json.dumps(src[k], ensure_ascii=False)[:400]}"
                )
    # naverShoppingSearchInfo 같은 키 안에 들어있을 가능성도 — 별도 키 전체 덤프
    print("\n[detailAttribute.optionInfo 키]")
    oi = (o.get("detailAttribute") or {}).get("optionInfo") or {}
    print(list(oi.keys()))


if __name__ == "__main__":
    asyncio.run(main())
