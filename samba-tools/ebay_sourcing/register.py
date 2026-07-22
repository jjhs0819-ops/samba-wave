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


async def _fetch_live_titles(session, acc_id: str) -> list[str]:
    """eBay 활성 리스팅 제목 전체 (Trading GetMyeBaySelling ActiveList).

    Inventory API 만으로는 레거시 리스팅이 안 잡혀 중복을 놓친다.
    """
    import xml.etree.ElementTree as ET

    import httpx
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.resolver import resolve_market_creds
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlmodel import select

    ns = {"e": "urn:ebay:apis:eBLBaseComponents"}
    acc = (
        await session.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == acc_id))
    ).scalars().first()
    ax = getattr(acc, "additional_fields", None) or {}
    cr = await resolve_market_creds(session, TENANT, market_type="ebay", store_key="store_ebay") or {}
    ec = EbayClient(
        cr.get("clientId") or cr.get("appId") or ax.get("clientId") or ax.get("appId", ""),
        cr.get("devId") or ax.get("devId", ""),
        cr.get("clientSecret") or cr.get("certId") or ax.get("clientSecret") or ax.get("certId", ""),
        cr.get("oauthToken") or cr.get("authToken") or ax.get("oauthToken") or ax.get("authToken", ""),
    )
    token = await ec._get_access_token()
    headers = {
        "X-EBAY-API-CALL-NAME": "GetMyeBaySelling",
        "X-EBAY-API-SITEID": "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "1349",
        "X-EBAY-API-IAF-TOKEN": token,
        "Content-Type": "text/xml",
    }
    titles: list[str] = []
    page = 1
    while True:
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            "<ActiveList><Include>true</Include>"
            f"<Pagination><EntriesPerPage>100</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>"
            "</ActiveList></GetMyeBaySellingRequest>"
        )
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.post(f"{ec._base_url}/ws/api.dll", content=xml, headers=headers)
        if r.status_code != 200:
            break
        root = ET.fromstring(r.text)
        titles += [
            (it.findtext("e:Title", "", ns) or "")
            for it in root.findall(".//e:ActiveList/e:ItemArray/e:Item", ns)
        ]
        total = root.findtext(".//e:ActiveList/e:PaginationResult/e:TotalNumberOfPages", "1", ns)
        if page >= int(total or 1):
            break
        page += 1
    return titles


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
    pol_id = _opt("--policy", POLICY)  # 기본=이베이_카드, 앨범은 --policy pol_01KY2VR2...

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            # dedup [최우선]: DB만 보면 안 된다. DB 행이 없어도 eBay에 라이브인
            # 리스팅이 있을 수 있음(2026-07-22 잉어킹 $117 중복등록 사고).
            # → eBay 활성 리스팅 제목과 직접 대조한다.
            import re as _re

            def _kw(x: str) -> set:
                stop = {"pokemon", "card", "game", "korean", "korea", "ver",
                        "sealed", "new", "the", "of", "and", "tcg", "official"}
                return set(_re.findall(r"[a-z0-9]+", (x or "").lower())) - stop

            live_titles = await _fetch_live_titles(s, acc_id)
            k = _kw(name_en)
            for lt in live_titles:
                lk = _kw(lt)
                if k and lk and len(k & lk) / len(k | lk) >= 0.55:
                    print(f"!! 이미 eBay에 라이브: '{lt[:60]}' → 신규등록 금지(revise 하세요)")
                    return
            # DB 보조 체크
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
            # [최우선] 판매가 = 정책 계산가. sale_price 를 원가로 두면 플러그인이
            # 그대로 판매가로 써서 마진·수수료 0 = 전량 적자 (2026-07-22 사고).
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
                source_site="BUNJANG", name=name, name_en=name_en,
                original_price=cost, sale_price=sale, cost=cost,
                status="active", sale_status="in_stock",
                source_url=f"https://m.bunjang.co.kr/products/{bpid}",
                site_product_id=bpid, images=[url],
                applied_policy_id=pol_id, tenant_id=TENANT, registered_accounts=[],
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
