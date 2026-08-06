import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
TARGET = "cp_01KYBVB1V0G9YKV8AKQR87CHMM"


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_read_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlalchemy import text as t
    from sqlmodel import select

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_read_session() as s:
            acc = (
                (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV)))
                .scalars()
                .first()
            )
            addf = acc.additional_fields or {}
            row = (
                await s.execute(
                    t("SELECT name, images, updated_at, market_product_nos FROM samba_collected_product WHERE id=:p"),
                    {"p": TARGET},
                )
            ).first()
            print("DB:", row)
        ec = EbayClient(
            app_id=addf.get("clientId") or acc.api_key,
            dev_id=addf.get("devId", ""),
            cert_id=addf.get("clientSecret") or acc.api_secret,
            refresh_token=addf.get("oauthToken") or acc.oauth_refresh_token,
        )
        offs = await ec.get_offers_by_sku(TARGET)
        if offs:
            o = offs[0]
            print("listingId:", o.get("listing", {}).get("listingId"))
            print("price:", o.get("pricingSummary", {}).get("price", {}))
            print("status:", o.get("status"), "qty:", o.get("availableQuantity"))
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
