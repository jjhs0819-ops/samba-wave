"""프록시 URL 전체 출력."""
import asyncio
import json
import sys

sys.path.insert(0, "/app/backend")
from sqlalchemy import text
from backend.db.orm import get_read_session


async def main() -> None:
    async with get_read_session() as s:
        row = (
            await s.execute(
                text("SELECT value FROM samba_settings WHERE key = 'proxy_config' LIMIT 1")
            )
        ).fetchone()
        val = row[0] if row else []
        if isinstance(val, str):
            val = json.loads(val)
        for item in val:
            if isinstance(item, dict):
                url = item.get("url", "")
                purposes = item.get("purposes", [])
                enabled = item.get("enabled", False)
                if "transmit" in purposes and enabled and url:
                    print(f"TRANSMIT_PROXY={url}")


asyncio.run(main())
