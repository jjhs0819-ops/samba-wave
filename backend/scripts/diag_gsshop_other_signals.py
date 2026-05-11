"""GS샵 추가 품절 신호 후보 검증:
1. salePsblGbn.ordButtn='N' (주문 버튼 비활성화)
2. sale_price=0 또는 cost=0
3. 이미지 누락(imgInfo 비어있음)
4. attrTypList(옵션) 비어있음
"""

import asyncio
import asyncpg
import httpx
import json
import re
from backend.core.config import settings


def extract_render_json(html: str) -> dict | None:
    m = re.search(r"var renderJson\s*=\s*(\{[\s\S]*?\});", html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


async def main():
    # 1) DB의 무작위 GSShop 상품 100개
    conn = await asyncpg.connect(
        host="172.18.0.2", port=5432,
        user=settings.read_db_user, password=settings.read_db_password,
        database=settings.read_db_name, ssl=False,
    )
    try:
        # DB 데이터 자체 이상치 분포 먼저
        print("[DB 이상치 분포]")
        for col in ["sale_price", "cost"]:
            r = await conn.fetchrow(
                f"SELECT COUNT(*) FILTER (WHERE {col}=0) AS zero, "
                f"COUNT(*) FILTER (WHERE {col} IS NULL) AS nul, COUNT(*) AS total "
                f"FROM samba_collected_product WHERE source_site='GSShop'"
            )
            print(f"  {col}: zero={r['zero']:,} null={r['nul']:,} total={r['total']:,}")
        r = await conn.fetchrow(
            "SELECT COUNT(*) AS no_opt FROM samba_collected_product "
            "WHERE source_site='GSShop' AND (options IS NULL OR options::text='[]')"
        )
        print(f"  options 빈/null: {r['no_opt']:,}")
        r = await conn.fetchrow(
            "SELECT COUNT(*) AS no_img FROM samba_collected_product "
            "WHERE source_site='GSShop' AND (images IS NULL OR images::text='[]')"
        )
        print(f"  images 빈/null: {r['no_img']:,}")

        # 무작위 100개 prdid 추출
        rows = await conn.fetch(
            "SELECT site_product_id, name, sale_price, cost FROM samba_collected_product "
            "WHERE source_site='GSShop' ORDER BY random() LIMIT 100"
        )
    finally:
        await conn.close()

    print(f"\n[실시간 호출] {len(rows)}개 prdid의 salePsblGbn / images / options 분포")
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
    }

    # 신호별 카운트
    sig_orderbutton_n = []
    sig_imgempty = []
    sig_attrempty = []
    sig_saleprice0 = []
    sig_prdsalest_n = []  # prdSaleSt != 'Y' 케이스

    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        for i, r in enumerate(rows, 1):
            sid = r["site_product_id"]
            try:
                resp = await client.get(
                    f"https://m.gsshop.com/prd/prd.gs?prdid={sid}", headers=headers
                )
                if resp.status_code != 200:
                    continue
                data = extract_render_json(resp.text)
                if not data:
                    continue
                prd = data.get("prd") or {}
                if not prd:
                    continue
                spg = prd.get("salePsblGbn") or {}
                ord_btn = spg.get("ordButtn", "?")
                bask_btn = spg.get("basktButtn", "?")
                prd_sale = prd.get("prdSaleSt", "?")
                attrs = prd.get("attrTypList") or []
                imgs = prd.get("imgInfo") or []
                if ord_btn != "Y":
                    sig_orderbutton_n.append((sid, r["name"], ord_btn, bask_btn, prd_sale))
                if not imgs:
                    sig_imgempty.append((sid, r["name"]))
                if not attrs:
                    sig_attrempty.append((sid, r["name"]))
                if prd_sale != "Y":
                    sig_prdsalest_n.append((sid, r["name"], prd_sale))
                if (r["sale_price"] or 0) == 0:
                    sig_saleprice0.append((sid, r["name"]))
            except Exception:
                pass
            if i % 25 == 0:
                print(f"  진행 {i}/100")
            await asyncio.sleep(0.15)

    print("\n[신호 발견 분포]")
    print(f"  1) ordButtn != 'Y' (주문불가): {len(sig_orderbutton_n)}")
    for sid, nm, ob, bb, ps in sig_orderbutton_n[:5]:
        print(f"     sid={sid} ordButtn={ob} basktButtn={bb} prdSaleSt={ps} | {(nm or '')[:40]!r}")
    print(f"  2) imgInfo 빈: {len(sig_imgempty)}")
    for sid, nm in sig_imgempty[:3]:
        print(f"     sid={sid} | {(nm or '')[:40]!r}")
    print(f"  3) attrTypList 빈(옵션없음): {len(sig_attrempty)}")
    for sid, nm in sig_attrempty[:3]:
        print(f"     sid={sid} | {(nm or '')[:40]!r}")
    print(f"  4) prdSaleSt != 'Y': {len(sig_prdsalest_n)}")
    for sid, nm, ps in sig_prdsalest_n[:5]:
        print(f"     sid={sid} prdSaleSt={ps} | {(nm or '')[:40]!r}")
    print(f"  5) DB sale_price=0: {len(sig_saleprice0)}")


if __name__ == "__main__":
    asyncio.run(main())
