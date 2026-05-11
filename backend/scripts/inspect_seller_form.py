"""셀러오피스 상품등록 폼 HTML 직접 조회 (사용자 쿠키 사용).

사용자가 공유한 TMALL_AUTH 쿠키로 1회 HTML fetch 후
crtfGrpObjClfCd0X 라디오 selected 상태 + 모든 인증관련 필드 추출.
"""

from __future__ import annotations

import asyncio
import re
import sys

import httpx


COOKIE = (
    "PCID=17705236411347157394102; "
    "TMALL_AUTH=I0bRBihoRSaLpVNtHtxNXqkQ3CRNcezoj43MlUYdg2m6Q4SK7%2BZerlNKqNDMQVJqQgpNJSXWm%2Bo7bU2zFcbivcJe1WgvUAIFR%2FfHGriqT%2Bk1s2gu3CMyV%2BkzFtat00QfKY%2Fd4GtB9QPrjInE6FwVZKIwFOw2gW%2FdrHuaScOPBX4EMdkesAJ3q6MtLPoJTY%2FSTwZFJfadsR7ySebF5lMrxPRVLCb0esKkvJ6XgDk%2FtDI4RYQGJFDTVlPMMlfSLjh7LIlgxHnYAW0d4HH97jI2sthudVzjSphnCtx6yfeXxI71gFNX0D41nhW%2BeeP0dMRyQcbmgu58l8lRjL%2FgQw1rwMiaQuUzp7WJLwCh6yhSYISLqPlschz%2BjG1NVLoGZHm9oZ8nSZYKmpIRLDtgZtwtBQ3gExMcTTFD3y4EWR6U2eLJH%2BUxXC5U6R%2BOSx0O6ES2SzKfLMal3AvQwauit%2Fo4Bk8P%2Fx6EwMyuZyJIOznCb0OegITpqOBYOZVIrboVwN0XoQESBtFK%2Br2ibH%2Bh%2BRgQTv3IjetpxH%2Bsg%2F1qhdVNlme1nUd0d6zUOUcgeGS0XALKZjr0tLH5MLwHM6hsjuOKpCTvE7F9WdU%2FcnilIcP353jWs4tn8mn32o4CdgYuo%2BX5%2FWtA2XycdnSd0hvdQO%2BGwb3JKl5yPu%2BcGK4UptBqKtUNHqC3G5cBRhRWQY1rt8loogA0LY2IPbR6gtGKGfKnZimP9H0k0nzCAYbMDWRs%2BPwtgBo1%2FGEh1Y%2F%2Fap4beTZRb3kMoxNHG0PtUWSJn4%2BN91%2B6ZR1Gjfm8miyltDzSA3zXippBnIKB2jPxWzkFFxkv5CEqWoyI4grJ8LqWWdWdj6qLm3f7edRQEbYWdsCKDdEhW4SdN7ZZWJAQZAu0OwgfzidEQwZ4b6TjcR9dUueR71Z985ylY7GQL%2Bt%2FY%2F6stCFiWfEOBsF%2BhebrMsZe%2BppfqEuaDD8JR%2B7pXZ7uUceyX7cdg8V6R5JWGzyzffXI7nV9mkwcjKNz4u8fLhZsrmZd5Ry8Nj6Dv8cs1Gff2Wgn%2BivyHKWwf5k6MMVB72CEj7GFYVa2jE%2BGnwRVaSwbIephdQWaThusvb3CiT9SBan01Li0rKLTKIIUqW2QKOE7g00MkYeqEdvekefHJdo19oOR3EbdBPCwFnTuBcSB8oMPxWgXxFcaE9G77ve4qHCztKEzJGq7%2BudVsuxOSWzE1bXMfGjKiFUKqWhWTYVv5Mt6fuKM8LgGChVCecwdYhKXkR0%3D; "
    "TMALL_STATIC=Y; TMALL_MNC=Nzc5NjQyMjY1NjA"
)


async def main() -> None:
    prd_no = sys.argv[1] if len(sys.argv) > 1 else "9316319232"
    url = f"https://soffice.11st.co.kr/product/ProductReg.tmall?method=viewForm&prdNo={prd_no}&formType=U"
    headers = {
        "Cookie": COOKIE,
        "Referer": "https://soffice.11st.co.kr/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.get(url, headers=headers)
    print(f"status={r.status_code} len={len(r.text)}")
    print("---SAMPLE---")
    print(r.text[:1500])
    print("---END---")
    if r.status_code != 200 or len(r.text) < 5000:
        sys.exit(1)

    html = r.text

    # crtf 관련 input 라디오 모두 추출
    print("\n[crtf 관련 input 모두]")
    pat = re.compile(
        r'<input[^>]*(?:id|name|class)=["\'][^"\']*[Cc]rtf[^"\']*["\'][^>]*>',
        re.I,
    )
    for m in pat.finditer(html):
        print("  ", m.group(0)[:300])

    # KC 관련 input
    print("\n[KC 관련 input]")
    pat2 = re.compile(r"<input[^>]*[Kk][Cc][^>]*>", re.I)
    for m in pat2.finditer(html):
        print("  ", m.group(0)[:300])

    # crtfGrpObjClfCd 키워드 자체로 검색
    print("\n[crtfGrpObjClfCd 키워드 출현 위치 (앞뒤 100자)]")
    for m in re.finditer(r"crtfGrpObjClfCd\d+", html):
        s = max(0, m.start() - 100)
        e = min(len(html), m.end() + 200)
        print(f"  …{html[s:e]}…")

    # CRTF_GRP / 인증 검색
    print("\n[인증/KC 키워드 영역 (radio + name)]")
    for m in re.finditer(
        r'name=["\']([^"\']*[Cc]rtf[^"\']*)["\'][^>]*value=["\']([^"\']*)["\'][^>]*(checked)?',
        html,
        re.I,
    ):
        print(
            f"  name={m.group(1)} value={m.group(2)} checked={m.group(3) is not None}"
        )


if __name__ == "__main__":
    asyncio.run(main())
