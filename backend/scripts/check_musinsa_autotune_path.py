"""autotune 코드 경로(쿠키+프록시) 그대로 무신사 API 호출 (진단용, 일회성)."""

import asyncio
import time

from backend.domain.samba.collector import refresher
from backend.domain.samba.proxy.musinsa import MusinsaClient


async def main() -> None:
    # 1) 쿠키 캐시 준비 (autotune 사이클 시작 시 호출되는 함수)
    await refresher._prepare_musinsa_cache()
    cookies = refresher._bulk_musinsa_cache.get("cookies") or []
    print(f"DB 쿠키 {len(cookies)}개 로드됨")
    if not cookies:
        print("쿠키 없음 → 오토튠 100% 실패 원인 확정")
        return

    # 2) autotune 컨텍스트로 표시 (프록시 사용 트리거)
    token = refresher._current_refresh_source.set("autotune")
    try:
        results: list[tuple[str, str]] = []
        for goods_no in ("6044992", "5981437", "5391418"):
            cookie = refresher._rotate_musinsa_cookie()
            proxy = refresher._get_rotated_proxy()
            client = MusinsaClient(cookie, proxy_url=proxy)
            shared = refresher._get_musinsa_shared_client(proxy)
            t0 = time.monotonic()
            try:
                detail = await asyncio.wait_for(
                    client.get_goods_detail(
                        goods_no,
                        refresh_only=True,
                        _shared_client=shared,
                    ),
                    timeout=45,
                )
                dt = time.monotonic() - t0
                gp = detail.get("goodsPrice") or {}
                msg = f"OK ({dt:.2f}s) price={gp.get('normalPrice')}"
            except asyncio.TimeoutError:
                dt = time.monotonic() - t0
                msg = f"TIMEOUT 45초 ({dt:.1f}s)"
            except Exception as e:
                dt = time.monotonic() - t0
                msg = f"ERROR {type(e).__name__} ({dt:.1f}s): {str(e)[:120]}"
            results.append((goods_no, msg))
            print(f"  [{goods_no}] proxy={proxy and proxy.split('@')[-1]} → {msg}")
    finally:
        refresher._current_refresh_source.reset(token)
        await refresher.reset_musinsa_shared_clients()

    ok = sum(1 for _, m in results if m.startswith("OK"))
    print(f"\n성공 {ok}/{len(results)}")


if __name__ == "__main__":
    asyncio.run(main())
