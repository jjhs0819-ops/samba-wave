"""신규 상품 eBay 등록 [컨테이너 실행].

진짜 신규(기존 리스팅 없음)만 사용. 이미 있으면 resource.py로 revise(중복 새등록=수수료+정책위반).
등록 전 dedup 체크(같은 name_en이 계정에 이미 있으면 중단).
고정가(--locked) 지원: price_locked로 오토튠 제외.

전제: /tmp/postit.jpg 검증완료 포스트잇.
※ 최초등록 시 title/category/aspects는 eBay 리서치 Sell Similar 베스트셀러 값 복제 권장(상위노출).

실행:
  docker cp samba-tools/ebay_sourcing/register.py local-samba-api-1:/tmp/register.py
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/register.py \
    <bunjang_pid> "<한글명>" "<영문명>" <category> <cost_krw> \
    [--locked <usd>] [--stock <n>] [--account <id>]
"""

import asyncio
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
POLICY = "pol_01KXD2K5JE2HHR53GZ1NGV0PGV"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"


def _opt(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.image.service import ImageTransformService
    from backend.domain.samba.proxy.ebay import EbayClient
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlalchemy import text as t
    from sqlmodel import select

    bpid, name, name_en, cat, cost = sys.argv[1:6]
    cost = float(cost)
    locked = _opt("--locked")
    stock = int(_opt("--stock", "1"))
    acc_id = _opt("--account", KV)

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            # dedup: 같은 name_en 이 이 계정에 이미 등록됐으면 중단
            dup = await s.execute(
                t(
                    "SELECT id FROM samba_collected_product WHERE name_en=:n "
                    "AND registered_accounts::text LIKE :a LIMIT 1"
                ),
                {"n": name_en, "a": f"%{acc_id}%"},
            )
            if dup.first():
                print("!! 이미 등록됨(중복 방지) → resource.py로 revise 하세요")
                return
            acc = (
                await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == acc_id))
            ).scalars().first()
            svc = ImageTransformService(s)
            url = await svc._save_image(
                open("/tmp/postit.jpg", "rb").read(),
                f"https://media.bunjang.co.kr/product/{bpid}_1.jpg",
            )
            p = SambaCollectedProduct(
                source_site="BUNJANG", name=name, name_en=name_en,
                original_price=cost, sale_price=cost, cost=cost,
                status="active", sale_status="in_stock",
                source_url=f"https://m.bunjang.co.kr/products/{bpid}",
                site_product_id=bpid, images=[url],
                applied_policy_id=POLICY, tenant_id=TENANT, registered_accounts=[],
            )
            if locked:
                p.price_locked = True
                p.locked_prices = {acc_id: float(locked)}
            p.stock_quantities = {acc_id: stock}
            s.add(p)
            await s.flush()
            pid = p.id
            res = await dispatch_to_market(
                s, "ebay", p.model_dump(), category_id=cat, account=acc,
                existing_product_no="",
            )
            print("register:", json.dumps(res, ensure_ascii=False)[:180])
            if res.get("success"):
                lid = res.get("data", {}).get("listingId") or res.get("product_no")
                p.registered_accounts = [acc_id]
                p.market_product_nos = {acc_id: lid}
                s.add(p)
                await s.commit()
                print("완료 product:", pid, "listing:", lid)
            else:
                await s.rollback()
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
