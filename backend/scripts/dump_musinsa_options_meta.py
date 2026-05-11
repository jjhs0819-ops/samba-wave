"""1377156 옵션 API 응답의 메타 키 식별."""

import asyncio
import json
from sqlalchemy import select
from backend.db.orm import get_read_session
from backend.api.v1.routers.samba.collector_common import get_musinsa_cookie
from backend.domain.samba.proxy.musinsa import MusinsaClient


async def main() -> None:
    async with get_read_session() as session:
        cookie = await get_musinsa_cookie(session)
    if not cookie:
        print("쿠키 없음")
        return

    import httpx

    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(
            f"https://goods-detail.musinsa.com/api2/goods/1377156/options",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": "https://www.musinsa.com/",
                "Cookie": cookie,
            },
        )
    data = (r.json().get("data") or {})
    print("[data 최상위 키]:", list(data.keys()))
    for k in data.keys():
        v = data[k]
        if isinstance(v, list):
            print(f"  {k}: list({len(v)}개)")
            if v and isinstance(v[0], dict):
                print(f"    [0] keys: {list(v[0].keys())[:20]}")
        elif isinstance(v, dict):
            print(f"  {k}: dict({list(v.keys())[:15]})")
        else:
            print(f"  {k}: {v!r}"[:100])


if __name__ == "__main__":
    asyncio.run(main())
