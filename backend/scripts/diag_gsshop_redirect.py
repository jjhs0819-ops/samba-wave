"""컨테이너 환경에서 GSShop 가짜 prdid 응답 status_code/Location/Body 확인."""

import asyncio
import httpx


async def main():
    urls = [
        "https://m.gsshop.com/prd/prd.gs?prdid=99999999999",
        "https://m.gsshop.com/prd/prd.gs?prdid=0",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
        "Accept": "text/html,application/xhtml+xml",
    }

    for url in urls:
        print(f"\n=== {url} ===")
        # follow_redirects=False
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as c:
            r = await c.get(url, headers=headers)
            print(f"  status: {r.status_code}")
            print(f"  Location: {r.headers.get('Location', '<none>')[:120]}")
            print(f"  Content-Length: {r.headers.get('Content-Length', '<none>')}")
            print(f"  body_len: {len(r.text)}")
            print(f"  body 처음 300자: {r.text[:300]!r}")


if __name__ == "__main__":
    asyncio.run(main())
