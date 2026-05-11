"""무신사 이중구조 옵션 API 응답 구조 진단.

실행: cd backend && .venv/Scripts/python.exe scripts/diagnose_musinsa_options.py 1373704
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx


async def diagnose(goods_no: str, cookie: str) -> None:
    BASE = "https://goods-detail.musinsa.com/api2/goods"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://www.musinsa.com/",
        "Cookie": cookie,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        print(f"\n=== 무신사 옵션 API 진단: {goods_no} ===")

        resp = await client.get(f"{BASE}/{goods_no}/options", headers=HEADERS)
        print(f"HTTP 상태: {resp.status_code}")

        if resp.status_code != 200:
            print(f"응답 오류: {resp.text[:500]}")
            return

        data = resp.json()
        inner = data.get("data") or {}

        print("\n[data 최상위 키 목록]")
        for k, v in inner.items():
            if isinstance(v, list):
                print(f"  {k}: list({len(v)}개)")
                if v:
                    print(
                        f"    첫 번째 항목 키: {list(v[0].keys()) if isinstance(v[0], dict) else type(v[0]).__name__}"
                    )
            elif isinstance(v, dict):
                print(f"  {k}: dict(키={list(v.keys())})")
            else:
                print(f"  {k}: {v!r}")

        # optionItems 상세
        items = inner.get("optionItems", [])
        print(f"\n[optionItems] 총 {len(items)}개")
        for i, item in enumerate(items[:5]):
            print(
                f"  [{i}] no={item.get('no')}, price={item.get('price')}, "
                f"activated={item.get('activated')}, "
                f"optionValues={[v.get('name') for v in item.get('optionValues', [])]}"
            )
        if len(items) > 5:
            print(f"  ... 및 {len(items) - 5}개 더")

        # addOptionItems 확인
        for key in [
            "addOptionItems",
            "addOnOptions",
            "subOptionItems",
            "optionAddItems",
            "additionalOptions",
            "optionGroups",
            "extraOptionItems",
        ]:
            if key in inner:
                v = inner[key]
                print(f"\n[{key}] 발견! 총 {len(v) if isinstance(v, list) else '?'}개")
                if isinstance(v, list) and v:
                    print(f"  구조: {json.dumps(v[:3], ensure_ascii=False, indent=2)}")

        # 전체 data 덤프 (축약)
        print("\n[전체 data 덤프 (처음 2000자)]")
        dumped = json.dumps(inner, ensure_ascii=False, indent=2)
        print(dumped[:2000])
        if len(dumped) > 2000:
            print(f"... (총 {len(dumped)}자)")


async def main() -> None:
    goods_no = sys.argv[1] if len(sys.argv) > 1 else "1373704"

    # DB에서 무신사 쿠키 로드
    try:
        from backend.db.orm import get_read_session
        from backend.api.v1.routers.samba.collector_common import get_musinsa_cookie

        async with get_read_session() as session:
            cookie = await get_musinsa_cookie(session)

        if cookie:
            print(f"DB에서 쿠키 로드 완료 ({len(cookie)}자)")
        else:
            print("DB에 무신사 쿠키 없음. MUSINSA_COOKIE 환경변수 시도...")
            import os

            cookie = os.environ.get("MUSINSA_COOKIE", "")
    except Exception as e:
        print(f"DB 로드 실패: {e}")
        import os

        cookie = os.environ.get("MUSINSA_COOKIE", "")

    if not cookie:
        print("쿠키 없음. 환경변수 MUSINSA_COOKIE에 쿠키 설정 후 재실행하세요.")
        return

    await diagnose(goods_no, cookie)


if __name__ == "__main__":
    asyncio.run(main())
