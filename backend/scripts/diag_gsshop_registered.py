"""GSShop 등록상품(registered_accounts != null) 중 prdSaleSt='N' 비율 확인."""

import asyncio
import asyncpg
import httpx
import re
import json as _json
from backend.core.config import settings


def extract_render_json(html: str) -> dict | None:
    m = re.search(r"var renderJson\s*=\s*(\{[\s\S]*?\});", html)
    if not m:
        return None
    try:
        return _json.loads(m.group(1))
    except Exception:
        return None


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2", port=5432,
        user=settings.read_db_user, password=settings.read_db_password,
        database=settings.read_db_name, ssl=False,
    )
    try:
        # 1) 등록상품 통계
        r = await conn.fetchrow(
            "SELECT "
            "COUNT(*) FILTER (WHERE registered_accounts::text NOT IN ('null','[]','')) AS registered, "
            "COUNT(*) FILTER (WHERE registered_accounts IS NULL OR registered_accounts::text IN ('null','[]','')) AS unregistered, "
            "COUNT(*) AS total "
            "FROM samba_collected_product WHERE source_site='GSShop'"
        )
        print(f"[GSShop 등록 상태]")
        print(f"  등록상품: {r['registered']:,}")
        print(f"  미등록: {r['unregistered']:,}")
        print(f"  전체: {r['total']:,}")

        # 2) 등록상품 50개 무작위 표본
        rows = await conn.fetch(
            "SELECT site_product_id, name, sale_status FROM samba_collected_product "
            "WHERE source_site='GSShop' "
            "AND registered_accounts::text NOT IN ('null','[]','') "
            "ORDER BY random() LIMIT 50"
        )
    finally:
        await conn.close()

    print(f"\n[실시간 호출] 등록상품 {len(rows)}개 → 실제 prdSaleSt 확인")
    if not rows:
        print("  [!] 등록상품 0건 — GSShop은 아직 등록된 상품이 없음")
        return

    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
    }
    sale_y = sale_n = ord_n = err = 0
    n_samples = []

    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        for i, r in enumerate(rows, 1):
            sid = r["site_product_id"]
            try:
                resp = await client.get(
                    f"https://m.gsshop.com/prd/prd.gs?prdid={sid}", headers=headers
                )
                if resp.status_code != 200:
                    err += 1
                    continue
                data = extract_render_json(resp.text)
                prd = (data or {}).get("prd") or {}
                if not prd:
                    err += 1
                    continue
                psv = prd.get("prdSaleSt", "?")
                spg = prd.get("salePsblGbn") or {}
                ord_btn = spg.get("ordButtn", "?")
                if psv != "Y":
                    sale_n += 1
                    if len(n_samples) < 10:
                        n_samples.append((sid, r["name"], psv, ord_btn, r["sale_status"]))
                else:
                    sale_y += 1
                if ord_btn != "Y":
                    ord_n += 1
            except Exception:
                err += 1
            await asyncio.sleep(0.15)

    print(f"\n[등록상품 prdSaleSt 분포]")
    print(f"  Y(정상판매): {sale_y}")
    print(f"  N(판매중지): {sale_n}")
    print(f"  err: {err}")
    print(f"  ordButtn != 'Y': {ord_n}")
    if n_samples:
        print(f"\n[N 케이스 샘플 — DB sale_status와 불일치 여부]")
        for sid, nm, psv, ob, ss in n_samples:
            mark = "❌ 불일치" if ss == "in_stock" and psv != "Y" else "✅ 일치"
            print(f"  {mark} sid={sid} prdSaleSt={psv} ord={ob} | DB={ss} | {(nm or '')[:40]!r}")


if __name__ == "__main__":
    asyncio.run(main())
