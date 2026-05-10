"""고경 계정의 채널상품 응답 구조 덤프 — origin 추출 경로 식별."""

import asyncio
import json
from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.smartstore import SmartStoreClient


GOGYUNG_ID = "ma_01KM04SY2TABXPNTTJFCVTX550"


async def main() -> None:
    async with get_read_session() as session:
        acc = await session.get(SambaMarketAccount, GOGYUNG_ID)
        extras = getattr(acc, "additional_fields", None) or {}
        cid = extras.get("clientId", "") or getattr(acc, "api_key", "") or ""
        csec = extras.get("clientSecret", "") or getattr(acc, "api_secret", "") or ""

    client = SmartStoreClient(cid, csec)
    r = await client._call_api("GET", "/v2/products/channel-products/13511265761")
    print("=== 응답 top-level keys ===")
    print(list(r.keys()))
    print("\n=== full JSON (first 3000 chars) ===")
    s = json.dumps(r, ensure_ascii=False, indent=2)
    print(s[:3000])


if __name__ == "__main__":
    asyncio.run(main())
