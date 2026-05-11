"""GSShop 품절 신호 진단 — 실제 상품들의 renderJson.prd에서 sold_out 관련 키 분포 확인."""

import asyncio
import asyncpg
from backend.core.config import settings
from backend.domain.samba.proxy.gsshop_sourcing import GsShopSourcingClient


SOLD_OUT_KEY_CANDIDATES = [
    "prdSaleSt",
    "saleStsCd",
    "isTempout",
    "tmpoutFlg",
    "soldOutFlg",
    "stockFlg",
    "saleYn",
    "prdSaleYn",
    "saleStatusCd",
    "availStockQty",
    "totStockQty",
    "stkQty",
    "buyPsbYn",
    "buyYn",
    "displayYn",
    "exhibitYn",
]


async def main():
    # 1) DB에서 GSShop 상품 site_product_id 30개 추출 (cost가 0인 것 우선 — 품절 의심)
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.read_db_user,
        password=settings.read_db_password,
        database=settings.read_db_name,
        ssl=False,
    )
    try:
        rows = await conn.fetch(
            """
            SELECT site_product_id, name, sale_price, cost, sale_status, last_refreshed_at
            FROM samba_collected_product
            WHERE source_site = 'GSShop'
            ORDER BY last_refreshed_at DESC NULLS LAST
            LIMIT 30
            """
        )
    finally:
        await conn.close()

    print(f"[DB] GSShop 상품 샘플 {len(rows)}개 추출")
    targets = [
        (r["site_product_id"], r["name"], r["sale_price"], r["cost"]) for r in rows
    ]

    # 2) 실제 GS샵 상세 페이지 가져와서 renderJson.prd의 sold-out 후보 키 + 값 분포 수집
    client = GsShopSourcingClient()

    key_counter: dict[str, dict[str, int]] = {k: {} for k in SOLD_OUT_KEY_CANDIDATES}
    full_dump_done = 0
    detail_fetch_fail = 0

    for sid, name, sale_p, cost in targets[:15]:
        try:
            _proxy = client._next_proxy()
            html = await client._fetch_mobile(sid, _proxy)
            if not html:
                detail_fetch_fail += 1
                continue
            data = client._extract_render_json(html)
            if not data:
                detail_fetch_fail += 1
                print(f"  [skip] {sid} renderJson 없음")
                continue
            prd = data.get("prd") or {}
            # 키-값 분포 누적
            for k in SOLD_OUT_KEY_CANDIDATES:
                v = prd.get(k, "<missing>")
                v_str = str(v)[:20]
                key_counter[k][v_str] = key_counter[k].get(v_str, 0) + 1
            # 처음 3개는 prd 키 전부 덤프
            if full_dump_done < 3:
                full_dump_done += 1
                keys = sorted(prd.keys())
                print(f"\n[FULL DUMP] sid={sid} name={(name or '')[:30]}")
                print(f"  prd keys ({len(keys)}): {keys}")
                # 품절·재고 단어 포함 키만 별도 강조
                soldish = [
                    k
                    for k in keys
                    if any(
                        t in k.lower()
                        for t in [
                            "sale",
                            "sold",
                            "stock",
                            "stk",
                            "tmpout",
                            "buy",
                            "avail",
                            "avl",
                            "qty",
                        ]
                    )
                ]
                print(f"  soldish keys ({len(soldish)}): {soldish}")
                for k in soldish:
                    print(f"    {k} = {repr(prd.get(k))[:80]}")
        except Exception as e:
            detail_fetch_fail += 1
            print(f"  [error] {sid}: {e}")

    print(f"\n[fetch 실패: {detail_fetch_fail}]")
    print("\n[KEY 분포] — 어떤 값들이 들어오는지 확인:")
    for k, dist in key_counter.items():
        if dist:
            print(f"  {k}: {dist}")

    # close 호출 — 일부 client 구현엔 없을 수 있음
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
