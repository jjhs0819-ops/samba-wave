"""KREAM → eBay 신규 등록 [컨테이너 실행] — 합성사진 선적용 버전.

kream_register.py와 달리 **미리 만들어둔 포스트잇 합성사진**을 등록에 바로 쓴다.
(등록 후 사진 갈아끼우기 금지 — 반드시 사진 먼저 만들고 등록)

실행:
  python3 kream_register_v2.py <kream_id> <category> "<영문타이틀>" --cost <원가> \
    --img /tmp/합성사진.png --sku <SKU> [--policy pol_...] [--stock 1]
"""

import asyncio
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
CARD_POLICY = "pol_01KXD2K5JE2HHR53GZ1NGV0PGV"  # 이베이_카드 (배송비 $9.90)


def _opt(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.image.service import ImageTransformService
    from backend.domain.samba.proxy.kream import KreamPartnerClient
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from backend.domain.samba.shipment.service import calc_market_price
    from sqlalchemy import text as t
    from sqlmodel import select

    kream_id = sys.argv[1]
    category = sys.argv[2]
    title = sys.argv[3]
    cost = float(_opt("--cost"))
    img_path = _opt("--img")
    sku = _opt("--sku")
    pol_id = _opt("--policy", CARD_POLICY)
    stock = int(_opt("--stock", "1"))

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            kacc = (
                (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.market_type == "kream")))
                .scalars()
                .first()
            )
            ext = kacc.additional_fields if isinstance(kacc.additional_fields, dict) else {}
            kcli = KreamPartnerClient(
                str(ext.get("apiService") or ""),
                str(ext.get("apiKey") or kacc.api_key or ""),
                str(ext.get("apiSecret") or kacc.api_secret or ""),
            )
            code, body = await kcli.get_product(int(kream_id))
            if code != 200:
                print("KREAM 조회 실패", code)
                return
            name_ko = body.get("translated_name") or body.get("name")

            # 합성사진 업로드
            svc = ImageTransformService(s)
            img_bytes = open(img_path, "rb").read()
            url = await svc._save_image(img_bytes, img_path)
            print("사진 업로드:", url)

            _pr, _mp = (
                await s.execute(t("SELECT pricing,market_policies FROM samba_policy WHERE id=:i"), {"i": pol_id})
            ).first()
            _pr = _pr if isinstance(_pr, dict) else json.loads(_pr or "{}")
            _mp = _mp if isinstance(_mp, dict) else json.loads(_mp or "{}")
            sale = float(calc_market_price(cost, _pr, "ebay", _mp) or cost)

            existing = (
                await s.execute(
                    t("SELECT id FROM samba_collected_product WHERE source_site='KREAM' AND site_product_id=:p"),
                    {"p": kream_id},
                )
            ).first()
            if existing:
                p = (
                    (await s.execute(select(SambaCollectedProduct).where(SambaCollectedProduct.id == existing[0])))
                    .scalars()
                    .first()
                )
                print("기존 row 재사용:", p.id)
            else:
                p = SambaCollectedProduct(
                    source_site="KREAM",
                    tenant_id=TENANT,
                    site_product_id=str(kream_id),
                    source_url=f"https://kream.co.kr/products/{kream_id}",
                    registered_accounts=[],
                )
            p.name = name_ko
            p.name_en = title
            p.original_price = cost
            p.sale_price = sale
            p.cost = cost
            p.status = "active"
            p.sale_status = "in_stock"
            p.images = [url]
            p.applied_policy_id = pol_id
            p.style_code = sku
            p.stock_quantities = {KV: stock}
            s.add(p)
            await s.flush()
            pid = p.id

            acc = (
                (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()
            )
            res = await dispatch_to_market(
                s, "ebay", p.model_dump(), category_id=category, account=acc, existing_product_no=""
            )
            print("register:", json.dumps(res, ensure_ascii=False)[:250])
            if res.get("success"):
                lid = res.get("data", {}).get("listingId") or res.get("product_no")
                p.registered_accounts = [KV]
                p.market_product_nos = {KV: lid}
                s.add(p)
                await s.commit()
                print("완료 product:", pid, "listing:", lid, "sku:", sku)
            else:
                await s.rollback()
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
