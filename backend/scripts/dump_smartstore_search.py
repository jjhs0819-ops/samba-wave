"""스마트스토어 search API 응답 구조 1건 덤프."""

import asyncio
import json
from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.smartstore import SmartStoreClient


GADI_ID = "ma_01KM04SY2TABXPNTTJFCVTX550"  # 고경


async def main() -> None:
    async with get_read_session() as session:
        acc = await session.get(SambaMarketAccount, GADI_ID)
        extras = getattr(acc, "additional_fields", None) or {}
        cid = extras.get("clientId", "") or getattr(acc, "api_key", "") or ""
        csec = extras.get("clientSecret", "") or getattr(acc, "api_secret", "") or ""

    client = SmartStoreClient(cid, csec)
    body = {
        "productStatusTypes": ["SALE"],
        "page": 1,
        "size": 3,
        "orderType": "NO",
    }
    res = await client._call_api("POST", "/v1/products/search", body=body)
    print("=== Top-level keys ===")
    print(list(res.keys()))
    print("\n=== First content keys ===")
    contents = res.get("contents", [])
    if contents:
        print(list(contents[0].keys()))
        print("\n=== First content full ===")
        print(json.dumps(contents[0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
