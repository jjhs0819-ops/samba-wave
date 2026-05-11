"""가디 계정의 기존 등록 상품에서 실제 사용된 leafCategoryId 추출."""

import asyncio
from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.smartstore import SmartStoreClient


GADI = "ma_01KM2K57Z8BQY984WC4HE93VQJ"


async def main() -> None:
    async with get_read_session() as session:
        acc = await session.get(SambaMarketAccount, GADI)
        extras = getattr(acc, "additional_fields", None) or {}
        cid = extras.get("clientId", "") or ""
        csec = extras.get("clientSecret", "") or ""
    client = SmartStoreClient(cid, csec)

    body = {"productStatusTypes": ["SALE"], "page": 1, "size": 5, "orderType": "NO"}
    res = await client._call_api("POST", "/v1/products/search", body=body)
    contents = res.get("contents", [])
    print(f"검색 결과 {len(contents)}건")
    for it in contents:
        on = it.get("originProductNo")
        if not on:
            continue
        try:
            r = await client.get_product(str(on))
            o = r.get("originProduct") or {}
            print(
                f"  origin={on} leafCat={o.get('leafCategoryId')} name={(o.get('name') or '')[:40]}"
            )
        except Exception as e:
            print(f"  origin={on} 조회실패: {e}")


if __name__ == "__main__":
    asyncio.run(main())
