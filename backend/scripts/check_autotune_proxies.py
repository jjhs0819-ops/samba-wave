"""autotune 용도 프록시 목록 + 각각 무신사 응답 테스트 (진단용, 일회성)."""

import asyncio
import json
import time

import asyncpg
import httpx

from backend.core.config import settings


async def main() -> None:
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        row = await conn.fetchrow(
            "SELECT value FROM samba_settings WHERE key='proxy_config'"
        )
    finally:
        await conn.close()

    if not row or not row["value"]:
        print("proxy_config 없음")
        return

    cfg = row["value"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg)

    autotune_proxies = []
    for p in cfg:
        if not p.get("enabled") or not p.get("url"):
            continue
        if "autotune" in (p.get("purposes") or []):
            autotune_proxies.append(p["url"])

    print(f"전체 프록시 {len(cfg)}개, autotune 활성 {len(autotune_proxies)}개\n")

    target = "https://goods-detail.musinsa.com/api2/goods/6044992"

    async def test(proxy_url: str) -> tuple[str, str]:
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(
                proxy=proxy_url, timeout=httpx.Timeout(15, connect=10)
            ) as c:
                r = await c.get(target)
                dt = time.monotonic() - t0
                return (proxy_url, f"HTTP {r.status_code} ({dt:.2f}s)")
        except httpx.ConnectTimeout:
            return (proxy_url, f"CONNECT_TIMEOUT ({time.monotonic() - t0:.1f}s)")
        except httpx.ReadTimeout:
            return (proxy_url, f"READ_TIMEOUT ({time.monotonic() - t0:.1f}s)")
        except Exception as e:
            return (proxy_url, f"ERROR {type(e).__name__}: {e}")

    results = await asyncio.gather(*[test(p) for p in autotune_proxies])
    for url, msg in results:
        # 프록시 URL의 인증정보 마스킹
        safe = url
        if "@" in url:
            head, tail = url.rsplit("@", 1)
            scheme = head.split("://")[0]
            safe = f"{scheme}://***@{tail}"
        print(f"  {safe} → {msg}")

    alive = sum(1 for _, m in results if m.startswith("HTTP 200"))
    print(f"\n생존 {alive}/{len(results)}")


if __name__ == "__main__":
    asyncio.run(main())
