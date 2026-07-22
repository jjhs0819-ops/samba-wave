"""KREAM 공식 API 소싱 → eBay 신규 등록 [컨테이너 실행].

KREAM 상품ID로 공식 파트너 API에서 이름·이미지·가격 자동 취득 → eBay 등록.
번장(재고1·품절churn)과 달리 KREAM=표준SKU·상시재고. KV(k-tcg_vault) 전용.

실행:
  docker cp samba-tools/ebay_sourcing/kream_register.py local-samba-api-1:/tmp/kream_register.py
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/kream_register.py \
    <kream_product_id> <category> "<영문타이틀(옵션)>" [--policy pol_kpopgoods_v1] [--stock 3]
"""

import asyncio
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"  # k-tcg_vault 전용 (마늘 금지)
GOODS_POLICY = "pol_kpopgoods_v1"


def _opt(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


async def main():
    import httpx

    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.image.service import ImageTransformService
    from backend.domain.samba.proxy.kream import KreamPartnerClient
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlalchemy import text as t
    from sqlmodel import select

    kream_id = sys.argv[1]
    category = sys.argv[2]
    title_override = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else ""
    pol_id = _opt("--policy", GOODS_POLICY)
    stock = int(_opt("--stock", "3"))
    price_key = _opt("--pricekey", "lowest_95_price")
    cost_override = _opt("--cost")  # 재고보유분: 실제 매입원가 직접 지정

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            # KREAM 공식 API 상품 조회
            kacc = (
                await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.market_type == "kream"))
            ).scalars().first()
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
            name_en = title_override or body.get("name")
            img_url = (body.get("main_images") or [None])[0]
            opts = body.get("options") or [{}]
            cost = None
            for o in opts:
                cost = o.get(price_key) or o.get("lowest_normal_price") or o.get("lowest_100_price")
                if cost:
                    break
            if cost_override:
                cost = float(cost_override)
            style = body.get("model_number") if body.get("model_number") not in ("-", "", None) else None
            print(f"KREAM: {name_en} | 원가={cost} | img={'Y' if img_url else 'N'} | style={style}")
            if not (name_en and img_url and cost):
                print("!! 필수값 누락 — 중단")
                return

            # dedup
            dup = await s.execute(
                t(
                    "SELECT id FROM samba_collected_product WHERE name_en=:n "
                    "AND registered_accounts::text LIKE :a LIMIT 1"
                ),
                {"n": name_en, "a": f"%{KV}%"},
            )
            if dup.first():
                print("!! 이미 등록됨 → resource로 revise 하세요")
                return

            acc = (
                await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV))
            ).scalars().first()
            svc = ImageTransformService(s)
            img_bytes = httpx.get(img_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).content
            url = await svc._save_image(img_bytes, img_url)

            # [최우선] 판매가 = 정책 계산가 (sale_price=원가 두면 마진0 적자)
            from backend.domain.samba.shipment.service import calc_market_price

            _pr, _mp = (
                await s.execute(
                    t("SELECT pricing,market_policies FROM samba_policy WHERE id=:i"),
                    {"i": pol_id},
                )
            ).first()
            _pr = _pr if isinstance(_pr, dict) else json.loads(_pr or "{}")
            _mp = _mp if isinstance(_mp, dict) else json.loads(_mp or "{}")
            sale = float(calc_market_price(float(cost), _pr, "ebay", _mp) or cost)

            p = SambaCollectedProduct(
                source_site="KREAM", name=name_ko, name_en=name_en,
                original_price=float(cost), sale_price=sale, cost=float(cost),
                status="active", sale_status="in_stock",
                source_url=f"https://kream.co.kr/products/{kream_id}",
                site_product_id=str(kream_id), images=[url],
                applied_policy_id=pol_id, tenant_id=TENANT, registered_accounts=[],
            )
            if style:
                p.style_code = style
            p.stock_quantities = {KV: stock}
            s.add(p)
            await s.flush()
            pid = p.id
            res = await dispatch_to_market(
                s, "ebay", p.model_dump(), category_id=category, account=acc,
                existing_product_no="",
            )
            print("register:", json.dumps(res, ensure_ascii=False)[:180])
            if res.get("success"):
                lid = res.get("data", {}).get("listingId") or res.get("product_no")
                p.registered_accounts = [KV]
                p.market_product_nos = {KV: lid}
                s.add(p)
                await s.commit()
                print("완료 product:", pid, "listing:", lid)
            else:
                await s.rollback()
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
