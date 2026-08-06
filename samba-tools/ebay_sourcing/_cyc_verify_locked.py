"""KV 고정가(price_locked) 상품 전수 조회 + 실제 eBay 리스팅 가격/재고/상태 대조 [컨테이너]."""
import asyncio
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_read_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlalchemy import text as _sa_text
    from sqlmodel import select

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_read_session() as s:
            acc = (
                (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV)))
                .scalars()
                .first()
            )
            addf_early = acc.additional_fields or {}
            res = await s.execute(
                _sa_text(
                    "SELECT id, name, locked_prices FROM samba_collected_product "
                    "WHERE price_locked = true AND registered_accounts::text LIKE :kv"
                ),
                {"kv": f"%{KV}%"},
            )
            kv_rows = [{"id": r[0], "name": r[1], "locked_prices": r[2]} for r in res.fetchall()]
        print(f"KV 등록계정 중 price_locked=true: {len(kv_rows)}건\n")

        addf = addf_early
        ec = EbayClient(
            app_id=addf.get("clientId") or acc.api_key,
            dev_id=addf.get("devId", ""),
            cert_id=addf.get("clientSecret") or acc.api_secret,
            refresh_token=addf.get("oauthToken") or acc.oauth_refresh_token,
        )
        for p in kv_rows:
            locked_usd = (p["locked_prices"] or {}).get(KV)
            offs = await ec.get_offers_by_sku(p["id"])
            if not offs:
                print(f"[{p['id']}] {p['name'][:24]} 잠금가=${locked_usd} -> offer 없음!")
                continue
            o = offs[0]
            live_price = o.get("pricingSummary", {}).get("price", {}).get("value")
            avail = o.get("availableQuantity")
            status = o.get("status")
            match = "OK" if str(live_price) == str(locked_usd) else "MISMATCH"
            print(
                f"[{p['id']}] {p['name'][:24]} 잠금가=${locked_usd} 라이브=${live_price} {match} "
                f"재고={avail} status={status}"
            )
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
