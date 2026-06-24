"""PlayAuto lookupProd 응답 구조 확인 — 프록시 포함."""

import asyncio
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text  # noqa: E402

from backend.db.orm import get_read_session  # noqa: E402


async def get_proxy_url(s) -> str:
    """DB에서 transmit 프록시 URL 조회."""
    row = (
        await s.execute(
            text(
                "SELECT value FROM samba_settings "
                "WHERE key = 'proxy_config' "
                "LIMIT 1"
            )
        )
    ).fetchone()
    if not row:
        return ""
    val = row[0]
    if isinstance(val, str):
        val = json.loads(val)
    # proxy_config 구조: [{purpose, url, ...}]
    if isinstance(val, list):
        for p in val:
            if isinstance(p, dict) and p.get("purpose") in ("transmit", "all"):
                url = p.get("url", "")
                if url:
                    return url
        if val and isinstance(val[0], dict):
            return val[0].get("url", "")
    return ""


async def main() -> None:
    async with get_read_session() as s:
        # 계정 api_key
        creds_row = (
            await s.execute(
                text(
                    "SELECT id, additional_fields "
                    "FROM samba_market_account "
                    "WHERE market_type = 'playauto' LIMIT 1"
                )
            )
        ).fetchone()
        extras = creds_row[1] or {}
        if isinstance(extras, str):
            extras = json.loads(extras)
        api_key = extras.get("apiKey", "")

        proxy_url = await get_proxy_url(s)

    print(f"api_key={str(api_key)[:8]}...")
    print(f"proxy_url={proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url}")

    if proxy_url:
        os.environ["PLAYAUTO_PROXY_URL"] = proxy_url

    from backend.domain.samba.proxy.playauto import PlayAutoClient  # noqa: E402

    client = PlayAutoClient(api_key=api_key)
    try:
        products = await client.get_products()
    finally:
        await client.close()

    if not products:
        print("lookupProd 응답 없음")
        return

    print(f"\nlookupProd 응답 수: {len(products):,}개")

    first = products[0]
    print(f"\n첫 번째 항목 키 목록: {list(first.keys())}")
    print(f"\n첫 번째 항목 전체:")
    for k, v in list(first.items()):
        print(f"  {k}: {str(v)[:100]!r}")


asyncio.run(main())
