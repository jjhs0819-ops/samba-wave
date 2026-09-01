"""잉어킹(398261291648) 연결 + 판매이력없는 유령 3건 eBay withdraw [컨테이너 실행]."""
import asyncio, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
MAGIKARP_CP = "cp_01KXX4HRMMJM9TMNV5YNZD76XM"
MAGIKARP_LISTING = "398261291648"

# 판매이력 없는 유령 3건 (item_id, cp_id)
GHOSTS = [
    ("398238201375", "cp_01KYYP82EW62JP8BDHC7M9H5QZ"),
    ("398238201815", "cp_01KYYP8GM6MYWHZSF7SGZ0S1DY"),
    ("398254962289", "cp_01KYBVBNPDK4WXZTMD12RJZRAE"),
]


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlmodel import select

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            acc = (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()
            addf = acc.additional_fields or {}
            ec = EbayClient(
                app_id=addf.get("clientId") or acc.api_key,
                dev_id=addf.get("devId", ""),
                cert_id=addf.get("clientSecret") or acc.api_secret,
                refresh_token=addf.get("oauthToken") or acc.oauth_refresh_token,
            )

            # 1) 잉어킹 연결
            p = (await s.execute(select(SambaCollectedProduct).where(SambaCollectedProduct.id == MAGIKARP_CP))).scalars().first()
            if p:
                p.registered_accounts = [KV]
                p.market_product_nos = {KV: MAGIKARP_LISTING}
                if not p.name_en:
                    p.name_en = "Pokemon Card Magikarp Promo (Korean)"
                s.add(p)
                await s.commit()
                print(f"잉어킹 연결 완료: {p.id} -> {MAGIKARP_LISTING}")
            else:
                print("!! 잉어킹 후보 상품 못찾음")

            # 2) 유령 3건 eBay withdraw (offer 조회 후 종료)
            for item_id, cp_id in GHOSTS:
                offs = await ec.get_offers_by_sku(cp_id)
                if not offs:
                    print(f"  {cp_id}: offer 못찾음 (item {item_id})")
                    continue
                offer_id = offs[0].get("offerId")
                r = await ec.withdraw_offer(offer_id)
                print(f"  {cp_id} (item {item_id}) withdraw: {r}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
