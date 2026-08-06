import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
TARGETS = ["cp_01KYXWJTYVJ4S6JSY2VV2C6746", "cp_01KYY8VS1WP0Y42EQVE154D289"]


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_read_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.proxy.ebay import EbayClient
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
        ec = EbayClient(
            app_id=addf.get("clientId") or acc.api_key,
            dev_id=addf.get("devId", ""),
            cert_id=addf.get("clientSecret") or acc.api_secret,
            refresh_token=addf.get("oauthToken") or acc.oauth_refresh_token,
        )
        for sku in TARGETS:
            offs = await ec.get_offers_by_sku(sku)
            if not offs:
                print(f"[{sku}] offer 없음")
                continue
            o = offs[0]
            print(
                f"[{sku}] status={o.get('status')} availableQuantity={o.get('availableQuantity')} "
                f"price={o.get('pricingSummary', {}).get('price', {})}"
            )
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
