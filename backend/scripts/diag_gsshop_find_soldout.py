"""GS샵 검색에서 isTempout=True 상품 찾아 상세 페이지 prd 키-값 덤프."""

import asyncio
from backend.domain.samba.proxy.gsshop_sourcing import GsShopSourcingClient


async def main():
    client = GsShopSourcingClient()

    # 검색에 잘 잡힐 만한 키워드 여러 개 시도 — 품절 상품 1~3개 찾기
    keywords = ["아이더", "노스페이스", "나이키", "아디다스", "푸마", "디스커버리", "조던", "뉴발란스"]
    soldout_targets: list[tuple[str, str]] = []

    for kw in keywords:
        try:
            items = await client.search_products(kw, size=60, url="")
        except Exception as e:
            print(f"[검색실패] {kw}: {e}")
            continue
        n_total = len(items)
        n_so = 0
        for it in items:
            if it.get("isSoldOut"):
                n_so += 1
                sid = it.get("siteProductId") or it.get("productId") or ""
                nm = it.get("name") or it.get("title") or ""
                if sid and len(soldout_targets) < 5:
                    soldout_targets.append((str(sid), nm))
        print(f"[검색] {kw}: 총 {n_total}건, 품절 {n_so}건")
        if len(soldout_targets) >= 5:
            break

    print(f"\n[품절 후보 {len(soldout_targets)}개]")
    for sid, nm in soldout_targets:
        print(f"  {sid} | {nm[:40]}")

    if not soldout_targets:
        print("\n[!] isTempout=True 상품을 못 찾음. 검색 응답 isTempout 값 분포 확인 필요")
        # 첫 키워드 검색 결과에서 isTempout 키 분포만 별도 확인
        items = await client.search_products("아이더", size=60, url="")
        from collections import Counter
        c = Counter(str(it.get("isSoldOut")) for it in items)
        print(f"isSoldOut 값 분포(아이더 60건): {dict(c)}")
        c2 = Counter(str(it.get("isTempout", "<missing>")) for it in items)
        print(f"raw isTempout 값 분포: {dict(c2)}")
        await _close(client)
        return

    # 품절 상품 상세 페이지 prd 키 덤프
    print("\n[품절 상품 상세 prd 키-값 덤프]")
    for sid, nm in soldout_targets[:3]:
        try:
            _proxy = client._next_proxy()
            html = await client._fetch_mobile(sid, _proxy)
            data = client._extract_render_json(html) if html else None
            if not data:
                print(f"\n  [{sid}] renderJson 없음 / html_len={len(html or '')}")
                # html 내 품절/일시품절 텍스트 검색
                for kw in ["품절", "일시품절", "재고없음", "판매중지", "SOLD OUT", "soldout"]:
                    if kw in (html or ""):
                        print(f"     HTML에 '{kw}' 발견")
                continue
            prd = data.get("prd") or {}
            print(f"\n  [{sid}] {nm[:40]}")
            print(f"     prdSaleSt = {prd.get('prdSaleSt', '<missing>')}")
            print(f"     salePsblGbn = {prd.get('salePsblGbn', '<missing>')}")
            print(f"     ordLimitQty = {prd.get('ordLimitQty', '<missing>')}")
            print(f"     ordQtyFlg = {prd.get('ordQtyFlg', '<missing>')}")
            # 모든 키 중 'Y'/'N' 값 가지면서 키 이름에 sale/sold/stock/tmpout/buy 포함된 것
            for k, v in prd.items():
                kl = k.lower()
                if any(t in kl for t in ['sale', 'sold', 'stock', 'tmpout', 'buy', 'avail', 'avl']):
                    print(f"     [{k}] = {repr(v)[:100]}")
        except Exception as e:
            print(f"  [{sid}] error: {e}")

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
