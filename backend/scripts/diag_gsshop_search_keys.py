"""GS샵 검색 결과의 raw item 키 구조 확인 — isTempout 대체 키 찾기."""

import asyncio
import json
import httpx
from backend.domain.samba.proxy.gsshop_sourcing import GsShopSourcingClient


async def main():
    client = GsShopSourcingClient()
    proxy = client._next_proxy()

    # _search_via_entry_data 흐름을 직접 흉내내서 raw entryData를 본다
    keyword = "아이더"
    # 검색 URL (코드 참조 — _search_via_entry_data가 사용하는 URL 패턴)
    url = f"https://m.gsshop.com/shop/sect/sectS.gs?sectid=&search={keyword}"

    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
        "Accept": "text/html,application/xhtml+xml",
    }

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as ac:
        r = await ac.get(url, headers=headers)
        html = r.text

    # entryData 추출
    marker = "var entryData = "
    start = html.find(marker)
    if start < 0:
        print(f"[!] entryData 없음. html_len={len(html)}")
        # 다른 패턴 검색
        for alt in ["var entryData=", "entryData =", "renderJson"]:
            idx = html.find(alt)
            print(f"  '{alt}' position: {idx}")
        await _close(client)
        return

    end = html.find(";\n", start)
    raw = html[start + len(marker):end if end > 0 else start + 200000]
    try:
        data = json.loads(raw)
    except Exception as e:
        # 끝 위치 다시 시도
        try:
            data = json.loads(raw.split("};")[0] + "}")
        except Exception as e2:
            print(f"[!] entryData JSON 파싱 실패: {e} / {e2}")
            print(f"raw 처음 500자: {raw[:500]}")
            await _close(client)
            return

    print(f"[entryData] top-level keys ({len(data)}): {list(data.keys())[:30]}")

    sample_item = None
    for k, v in data.items():
        if isinstance(v, list) and v:
            for it in v:
                if isinstance(it, dict) and it.get("dealNo"):
                    sample_item = it
                    print(f"\n[sample list key] '{k}' (len={len(v)})")
                    break
        if sample_item:
            break

    if not sample_item:
        print("[!] dealNo 가진 아이템 없음")
        await _close(client)
        return

    keys = sorted(sample_item.keys())
    print(f"\n[item keys] ({len(keys)}):")
    for k in keys:
        v = sample_item[k]
        v_repr = repr(v)[:80]
        print(f"  {k} = {v_repr}")

    # 모든 아이템에서 'tempout'/'soldout'/'sale' 등 포함 키 분포
    from collections import Counter
    soldish_keys = set()
    for k, v in data.items():
        if not isinstance(v, list):
            continue
        for it in v:
            if not isinstance(it, dict):
                continue
            for ik in it.keys():
                ikl = ik.lower()
                if any(t in ikl for t in ['tempout', 'soldout', 'salest', 'salepsbl', 'stock', 'buyy', 'buyps', 'avail', 'sale_st']):
                    soldish_keys.add(ik)

    print(f"\n[soldish keys 발견]: {sorted(soldish_keys)}")

    # 그 키들의 값 분포
    for sk in sorted(soldish_keys):
        c: Counter = Counter()
        for k, v in data.items():
            if not isinstance(v, list):
                continue
            for it in v:
                if isinstance(it, dict) and it.get("dealNo"):
                    c[str(it.get(sk, "<missing>"))] += 1
        print(f"  {sk}: {dict(c.most_common(8))}")

    await _close(client)


async def _close(client):
    close = getattr(client, "close", None)
    if close:
        try:
            res = close()
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
