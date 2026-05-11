"""6개 등록상품(prdSaleSt='N')에 plugin.refresh() 직접 호출 → 진단."""

import asyncio
import asyncpg
from backend.core.config import settings
from backend.domain.samba.plugins.sourcing.gsshop import GsShopSourcingPlugin


TARGETS = ["1114482436", "1117278628", "1109875187", "1112124919", "1112295610", "1109875192"]


class FakeProduct:
    def __init__(self, sid, name, sale_status, sale_price, cost, options):
        self.id = f"col_gsshop_{sid}"
        self.site_product_id = sid
        self.name = name
        self.sale_status = sale_status
        self.sale_price = sale_price
        self.cost = cost
        self.options = options or []


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2", port=5432,
        user=settings.read_db_user, password=settings.read_db_password,
        database=settings.read_db_name, ssl=False,
    )
    try:
        rows = await conn.fetch(
            "SELECT site_product_id, name, sale_status, sale_price, cost, options "
            "FROM samba_collected_product "
            "WHERE source_site='GSShop' AND site_product_id = ANY($1::text[])",
            TARGETS,
        )
    finally:
        await conn.close()

    plugin = GsShopSourcingPlugin()
    print(f"[verify] plugin.refresh() 직접 호출 — {len(rows)}개\n")
    for r in rows:
        p = FakeProduct(
            r["site_product_id"], r["name"], r["sale_status"],
            r["sale_price"], r["cost"], r["options"],
        )
        try:
            # plugin 내부 except 우회 — get_product_detail 직접 호출해 detail 구조 노출
            from backend.domain.samba.proxy.gsshop_sourcing import GsShopSourcingClient
            client = GsShopSourcingClient()
            detail = await client.get_product_detail(r["site_product_id"], refresh_only=True)
            print(f"  sid={r['site_product_id']} detail keys: {list(detail.keys()) if detail else 'EMPTY'}")
            opts = detail.get("options", []) if detail else []
            print(f"    options type={type(opts).__name__} len={len(opts)} first={opts[:1] if opts else 'N/A'}")
            print(f"    saleStatus={detail.get('saleStatus') if detail else '?'}, isOutOfStock={detail.get('isOutOfStock') if detail else '?'}")
            # 진짜 plugin.refresh()로도 한 번
            import traceback as _tb
            try:
                result = await plugin.refresh(p)
            except Exception as e:
                _tb.print_exc()
                continue
            print(f"  sid={r['site_product_id']}")
            print(f"    new_sale_status: {result.new_sale_status}")
            print(f"    changed: {result.changed}")
            print(f"    stock_changed: {result.stock_changed}")
            print(f"    deleted_from_source: {result.deleted_from_source}")
            print(f"    error: {result.error}")
            if result.new_sale_price:
                print(f"    new_sale_price: {result.new_sale_price}")
        except Exception as e:
            print(f"  sid={r['site_product_id']} EXCEPTION: {type(e).__name__}: {e}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
