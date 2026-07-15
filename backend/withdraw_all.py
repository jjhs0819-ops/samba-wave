import asyncio
import sys

sys.path.insert(0, ".")


async def main():
    from sqlmodel import select
    from backend.db.orm import get_read_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.proxy.ebay import EbayClient

    async with get_read_session() as session:
        result = await session.execute(
            select(SambaMarketAccount).where(
                SambaMarketAccount.id == "ma_01KWVPQYKN4RRMVRKBF4DYV069"
            )
        )
        account = result.scalars().first()
        extras = account.additional_fields or {}
        client = EbayClient(
            app_id=extras.get("clientId")
            or extras.get("appId")
            or account.api_key
            or "",
            dev_id="",
            cert_id=extras.get("clientSecret")
            or extras.get("certId")
            or account.api_secret
            or "",
            refresh_token=extras.get("oauthToken") or extras.get("authToken", "") or "",
            sandbox=False,
        )

        # 계정 전체 인벤토리 나열
        skus = []
        offset = 0
        while True:
            resp = await client._call(
                "GET", f"/sell/inventory/v1/inventory_item?limit=100&offset={offset}"
            )
            items = resp.get("inventoryItems", []) or []
            skus.extend(i["sku"] for i in items)
            total = int(resp.get("total", 0) or 0)
            offset += 100
            if offset >= total or not items:
                break
        print("전체 SKU:", len(skus))

        ended = skipped = failed = 0
        for sku in skus:
            for attempt in range(3):
                try:
                    offers = await client.get_offers_by_sku(sku)
                    if not offers:
                        skipped += 1
                        break
                    o = offers[0]
                    st = (o.get("listing") or {}).get("listingStatus", "")
                    if st != "ACTIVE":
                        skipped += 1
                        break
                    await client._call(
                        "POST",
                        f"/sell/inventory/v1/offer/{o['offerId']}/withdraw",
                        {},
                    )
                    ended += 1
                    print("판매중지:", sku)
                    break
                except Exception as e:
                    if attempt == 2:
                        failed += 1
                        print("실패:", sku, repr(e)[:60])
                    else:
                        await asyncio.sleep(3)
        print(f"요약: 중지 {ended} / 스킵(이미 비활성 등) {skipped} / 실패 {failed}")


asyncio.run(main())
