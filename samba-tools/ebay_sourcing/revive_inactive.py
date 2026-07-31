"""비활성(미판매 종료) 리스팅 복구 루틴 [컨테이너 실행].

왜 비활성이 되나:
  GTC + OutOfStockControl=true 상태에서 재고가 0이 되면 eBay가 리스팅을 내린다.
  번장 소스는 대부분 재고 1개라 소스가 죽으면 재고 0 → 비활성으로 떨어진다.
  즉 "잘 팔리던 상품이 자꾸 비활성" = 상품이 나쁜 게 아니라 소스가 죽은 것.

복구 절차:
  eBay UnsoldList 조회 → 같은 카드의 살아있는 번장 매물 재탐색 →
  원가(가격+최저배송비)·정책가 재계산 → 신규 등록(insertion fee 발생).

주의:
  - 라이브에 같은 상품이 이미 있으면 건너뛴다(중복등록 금지).
  - 다품목 혼합 매물(제목에 쉼표/여러 카드)은 제외.
  - 최저가 1번째는 허위매물이 잦아 2번째 가격을 택한다.

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/revive_inactive.py [--dry] [--only "Meowth"]
"""

import asyncio
import io
import json
import re
import sys
import xml.etree.ElementTree as ET

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
CARD_POLICY = "pol_01KXD2K5JE2HHR53GZ1NGV0PGV"
NS = {"e": "urn:ebay:apis:eBLBaseComponents"}
H = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://m.bunjang.co.kr/",
}
BAD = (
    "삽니다",
    "구해요",
    "구합니다",
    "구매",
    "매입",
    "교환",
    "대리",
    "예약",
    "원합니다",
    "일괄",
    "랜덤",
    # 굿즈/번들 = 카드 아님. 카드 제목으로 등록되던 재발원인(2026-07-27 잉어킹 교통카드·키링 사고)
    "키링",
    "키홀더",
    "교통카드",
    "이즐",
    "뱃지",
    "배지",
    "아크릴",
    "거치대",
    "스탠드",
    "시계",
    "워치",
    "스트랩",
    "인형",
    "포스터",
    "우산",
    "텀블러",
    "엽서",
    "틴케이스",
    "굿즈",
    "스티커",
    "슬리브",
    "탑로더",
    "쿠션",
    "부채",
    "마그넷",
    "자석",
    "브로마이드",
    "키캡",
    "파우치",
    "빈티지",
    "정품",
    "키홀더",
    "볼펜",
    "노트",
    "배찌",
    "홀더",
    "스티키",
)
# 영문 리스팅 제목 → 번장 검색용 한글명. 번장은 한글로만 검색되므로 필수.
EN2KO = {
    "meowth": "냐옹",
    "magikarp": "잉어킹",
    "venusaur": "이상해꽃",
    "charizard": "리자몽",
    "blastoise": "거북왕",
    "mewtwo": "뮤츠",
    "riolu": "리오르",
    "absol": "앱솔",
    "garchomp": "한카리아스",
    "reshiram": "레시라무",
    "zekrom": "제크로무",
    "machoke": "근육몬",
    "horsea": "쏘드라",
    "snivy": "쥬토리",
    "tepig": "뚜꼬",
    "mew": "뮤",
}


def min_fee(trade: dict) -> int:
    """번장 배송비는 최저 옵션 기준(반값택배 포함)."""
    if (trade or {}).get("freeShipping"):
        return 0
    specs = (trade or {}).get("shippingSpecs") or {}
    fees = [int(v.get("fee") or 0) for v in specs.values() if isinstance(v, dict)]
    return min(fees) if fees else 0


def kw_of(title: str) -> str:
    """영문 리스팅 제목 → 번장 검색어.

    번장은 한글로만 검색되므로 포켓몬 영문명을 한글로 바꾼다.
    품번(예: 114/080)이 있으면 함께 넣어 정확도를 올린다.
    """
    low = title.lower()
    ko = next((v for k, v in EN2KO.items() if k in low), "")
    num = (
        (re.search(r"\d{2,3}/\d{2,3}", title) or [""])[0]
        if re.search(r"\d{2,3}/\d{2,3}", title)
        else ""
    )
    rare = "sar" if "sar" in low else ("ar" if re.search(r"ar", low) else "")
    parts = [x for x in (ko, rare, num) if x]
    if parts:
        return " ".join(parts)
    t = re.sub(r"(Pokemon|Korean|Card|TCG|NM|Japanese)", " ", title, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()[:30]


def _tok(x: str) -> set:
    stop = {"pokemon", "card", "korean", "korea", "tcg", "new", "sealed", "the", "of"}
    return set(re.findall(r"[a-z0-9]+", (x or "").lower())) - stop


async def bunjang_pick(c, query: str, target_ko: str = ""):
    """SELLING·단일품목만 모아 2번째 저가를 고른다(1번째는 허위매물 잦음)."""
    r = await c.get(
        "https://api.bunjang.co.kr/api/1/find_v2.json",
        params={"q": query, "order": "score", "page": 0, "n": 40},
    )
    cand = []
    for it in r.json().get("list", []):
        nm = it.get("name", "")
        try:
            pr = int(it.get("price", 0))
        except Exception:
            continue
        if (
            str(it.get("status")) != "0"
            or any(b in nm for b in BAD)
            or nm.count(",") >= 1
        ):
            continue
        # [중요] 쉼표 없이 여러 카드를 나열한 매물이 많다("sar ar sr 카드 팔아요 A B C").
        # 레어도 토큰이 2개 이상이거나 제목이 지나치게 길면 다중매물로 보고 제외.
        rar = len(re.findall(r"(?<![a-z])(sar|ar|sr|ur|rr|hr)(?![a-z])", nm.lower()))
        if rar >= 2 or len(nm) > 34:
            continue
        # 대상 카드명이 제목에 실제로 있어야 한다(엉뚱한 카드 매칭 방지)
        if target_ko and target_ko not in nm:
            continue
        if pr < 3000 or pr > 300000:
            continue
        cand.append((pr, str(it.get("pid")), nm))
    cand.sort()
    picks = cand[1:3] or cand[:1]
    for pr, pid, nm in picks:
        d = (
            (
                await c.get(
                    f"https://api.bunjang.co.kr/api/pms/v1/products/{pid}/detail/web"
                )
            )
            .json()
            .get("data", {})
            .get("product", {})
        )
        if d.get("saleStatus") != "SELLING":
            continue
        return pid, int(d.get("price") or 0) + min_fee(d.get("trade")), nm
    return None, 0, ""


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.resolver import resolve_market_creds
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.image.service import ImageTransformService
    from backend.domain.samba.proxy.ebay import EbayClient
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from backend.domain.samba.shipment.service import calc_market_price
    from sqlalchemy import text as t
    from sqlmodel import select

    dry = "--dry" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else ""

    tok = current_tenant_id.set(TENANT)
    async with get_write_session() as s:
        acc = (
            (
                await s.execute(
                    select(SambaMarketAccount).where(SambaMarketAccount.id == KV)
                )
            )
            .scalars()
            .first()
        )
        ax = getattr(acc, "additional_fields", None) or {}
        cr = (
            await resolve_market_creds(
                s, TENANT, market_type="ebay", store_key="store_ebay"
            )
            or {}
        )
        ec = EbayClient(
            cr.get("clientId")
            or cr.get("appId")
            or ax.get("clientId")
            or ax.get("appId", ""),
            cr.get("devId") or ax.get("devId", ""),
            cr.get("clientSecret")
            or cr.get("certId")
            or ax.get("clientSecret")
            or ax.get("certId", ""),
            cr.get("oauthToken")
            or cr.get("authToken")
            or ax.get("oauthToken")
            or ax.get("authToken", ""),
        )
        token = await ec._get_access_token()
        hdr = {
            "X-EBAY-API-CALL-NAME": "GetMyeBaySelling",
            "X-EBAY-API-SITEID": "0",
            "X-EBAY-API-COMPATIBILITY-LEVEL": "1349",
            "X-EBAY-API-IAF-TOKEN": token,
            "Content-Type": "text/xml",
        }

        async def lst(name):
            xml = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
                f"<{name}><Include>true</Include><Pagination><EntriesPerPage>200</EntriesPerPage>"
                f"<PageNumber>1</PageNumber></Pagination></{name}>"
                "</GetMyeBaySellingRequest>"
            )
            async with httpx.AsyncClient(timeout=40) as c:
                r = await c.post(f"{ec._base_url}/ws/api.dll", content=xml, headers=hdr)
            root = ET.fromstring(r.text)
            return [
                (i.findtext("e:ItemID", "", NS), i.findtext("e:Title", "", NS))
                for i in root.findall(f".//e:{name}/e:ItemArray/e:Item", NS)
            ]

        unsold = await lst("UnsoldList")
        live = {t2.lower() for _, t2 in await lst("ActiveList")}
        print(f"비활성 {len(unsold)} / 라이브 {len(live)}")

        async with httpx.AsyncClient(timeout=20, headers=H) as bc:
            for iid, title in unsold:
                if only and only.lower() not in title.lower():
                    continue
                # [중요] 제목 완전일치로만 보면 표현이 조금 달라진 중복을 놓친다 → 토큰 유사도로 판정
                k = _tok(title)
                dup = any(
                    k and _tok(lt) and len(k & _tok(lt)) / len(k | _tok(lt)) >= 0.5
                    for lt in live
                )
                if dup:
                    print(f"SKIP(라이브에 이미 있음) {title[:46]}")
                    continue
                # [중요] 같은 카드가 이미 라이브면 스킵(중복등록=계정정지). 제목 표현이 달라도
                # 포켓몬 영문명이 라이브 제목에 있으면 동일 카드로 본다(2026-07-27 잉어킹 중복사고).
                en_name = next((kk for kk in EN2KO if kk in title.lower()), "")
                if en_name and any(en_name in lt for lt in live):
                    print(f"SKIP(같은 카드 라이브) {title[:46]}")
                    continue
                q = kw_of(title)
                ko = next((v for kk, v in EN2KO.items() if kk in title.lower()), "")
                pid, cost, nm = await bunjang_pick(bc, q, ko)
                if not pid:
                    print(f"NOSRC {title[:46]}")
                    continue
                pr, mp = (
                    await s.execute(
                        t(
                            "SELECT pricing,market_policies FROM samba_policy WHERE id=:i"
                        ),
                        {"i": CARD_POLICY},
                    )
                ).first()
                pr = pr if isinstance(pr, dict) else json.loads(pr or "{}")
                mp = mp if isinstance(mp, dict) else json.loads(mp or "{}")
                sale = float(calc_market_price(float(cost), pr, "ebay", mp) or cost)
                print(
                    f"{'DRY' if dry else 'RUN'} {title[:40]} ← 번장{pid} 원가{cost} 판매{int(sale)}원 | {nm[:28]}"
                )
                if dry:
                    continue
                src = f"https://media.bunjang.co.kr/product/{pid}_1_w856.jpg"
                url = await ImageTransformService(s)._save_image(
                    httpx.get(src, timeout=30, headers=H).content, src
                )
                p = SambaCollectedProduct(
                    source_site="BUNJANG",
                    name=nm,
                    name_en=title,
                    original_price=float(cost),
                    sale_price=sale,
                    cost=float(cost),
                    status="active",
                    sale_status="in_stock",
                    source_url=f"https://m.bunjang.co.kr/products/{pid}",
                    site_product_id=pid,
                    images=[url],
                    applied_policy_id=CARD_POLICY,
                    tenant_id=TENANT,
                    registered_accounts=[],
                )
                p.stock_quantities = {KV: 1}
                s.add(p)
                await s.flush()
                res = await dispatch_to_market(
                    s,
                    "ebay",
                    p.model_dump(),
                    category_id="183454",
                    account=acc,
                    existing_product_no="",
                )
                if res.get("success"):
                    lid = res.get("data", {}).get("listingId") or res.get("product_no")
                    p.registered_accounts = [KV]
                    p.market_product_nos = {KV: lid}
                    s.add(p)
                    await s.commit()
                    print(f"   복구완료 → listing {lid}")
                else:
                    await s.rollback()
                    print(f"   실패: {str(res.get('message'))[:70]}")
    current_tenant_id.reset(tok)


asyncio.run(main())
