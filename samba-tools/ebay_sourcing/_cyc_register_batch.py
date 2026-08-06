"""레쿠쟈 신규 배치등록 [컨테이너 실행, 진짜 신규만].

register.py 로직(dedup: eBay 라이브 제목 + DB) 재사용, 배치용으로 확장.
"""
import asyncio
import io
import json
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from scipy import ndimage  # noqa: E402

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
POLICY = "pol_01KXD2K5JE2HHR53GZ1NGV0PGV"
CAT_SINGLE = "183454"
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.bunjang.co.kr/"}

ITEMS = [
    {"pid": "416387388", "name": "포켓몬카드 레쿠자 sar", "name_en": "Pokemon Card Rayquaza SAR (Korean)", "cost": 300000},
    {"pid": "422161945", "name": "레쿠쟈 CSR [BRG10]", "name_en": "Pokemon Card Rayquaza CSR BRG10 (Korean)", "cost": 220000},
    {"pid": "413382631", "name": "레쿠쟈v 특일 (brg10)", "name_en": "Pokemon Card Rayquaza V Rare BRG10 (Korean)", "cost": 250000},
    {"pid": "422784295", "name": "포켓몬카드 레쿠쟈 V 특일 9등급입니다", "name_en": "Pokemon Card Rayquaza V Rare Grade 9 (Korean)", "cost": 130000},
    {"pid": "423220908", "name": "포켓몬카드 레쿠쟈v 특일", "name_en": "Pokemon Card Rayquaza V Rare (Korean)", "cost": 70000},
    {"pid": "417746103", "name": "포켓몬카드 brg9 레쿠쟈 V", "name_en": "Pokemon Card Rayquaza V BRG9 (Korean)", "cost": 150000},
    {"pid": "421751589", "name": "포켓몬카드 레쿠쟈EX 에메랄드브레이크 25주년 기념 카드", "name_en": "Pokemon Card Rayquaza ex Emerald Break 25th Anniversary (Korean)", "cost": 188100},
    {"pid": "423229595", "name": "팀배틀 프로모 레쿠쟈ex brg9", "name_en": "Pokemon Card Rayquaza ex Team Battle Promo BRG9 (Korean)", "cost": 85000},
    {"pid": "422742193", "name": "포켓몬카드 스톰에메랄드 메가 레쿠쟈 EX sr 095/076", "name_en": "Pokemon Card Mega Rayquaza ex SR Storm Emerald 095/076 (Korean)", "cost": 100000},
    {"pid": "417332780", "name": "포켓몬카드 brg9 레쿠쟈 VMAX", "name_en": "Pokemon Card Rayquaza VMAX BRG9 (Korean)", "cost": 40000},
    {"pid": "423159486", "name": "포켓몬카드 레쿠쟈 VMAX 다이맥스 rrr", "name_en": "Pokemon Card Rayquaza VMAX RRR (Korean)", "cost": 5500},
    {"pid": "423075288", "name": "포켓몬 카드 레쿠쟈 VMAX 다이맥스", "name_en": "Pokemon Card Rayquaza VMAX Dynamax (Korean)", "cost": 5000},
    {"pid": "422509102", "name": "포켓몬카드 레쿠쟈 vmax RRR s7R 047/067", "name_en": "Pokemon Card Rayquaza VMAX RRR s7R 047/067 (Korean)", "cost": 4800},
    {"pid": "422995661", "name": "포켓몬 카드 레쿠쟈 V SR", "name_en": "Pokemon Card Rayquaza V SR (Korean)", "cost": 18000},
    {"pid": "423017138", "name": "레쿠쟈 V SR 특일", "name_en": "Pokemon Card Rayquaza V SR Rare (Korean)", "cost": 99000},
    {"pid": "422842088", "name": "레쿠쟈 V 프로모", "name_en": "Pokemon Card Rayquaza V Promo (Korean)", "cost": 10000},
    {"pid": "419320020", "name": "포켓몬 카드 레쿠쟈 V RR", "name_en": "Pokemon Card Rayquaza V RR (Korean)", "cost": 3000},
]


def _bg_color(a):
    h, w = a.shape[:2]
    bt = max(3, int(h * 0.04))
    bs = max(3, int(w * 0.04))
    ring = np.concatenate(
        [a[:bt].reshape(-1, 3), a[-bt:].reshape(-1, 3), a[:, :bs].reshape(-1, 3), a[:, -bs:].reshape(-1, 3)]
    )
    q = (ring // 16) * 16
    keys, counts = np.unique(q, axis=0, return_counts=True)
    return keys[int(np.argmax(counts))].astype(float) + 8


def _bbox_from_mask(m, w, h):
    m = ndimage.binary_opening(m, iterations=1)
    lbl, n = ndimage.label(m)
    if n == 0:
        return None
    sizes = ndimage.sum(m, lbl, range(1, n + 1))
    m = lbl == (int(np.argmax(sizes)) + 1)
    rows_w = m.sum(1)
    maxw = rows_w[: int(h * 0.6)].max() if rows_w[: int(h * 0.6)].size else rows_w.max()
    maxw = max(maxw, rows_w.max() * 0.9)
    good = np.where(rows_w > 0.55 * maxw)[0]
    if len(good) < 3:
        ys, xs = np.where(m)
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    y0, y1 = int(good.min()), int(good.max())
    cols = np.where(m[y0 : y1 + 1].sum(0) > 0.30 * (y1 - y0 + 1))[0]
    if len(cols) < 3:
        xs = np.where(m.any(0))[0]
        x0, x1 = int(xs.min()), int(xs.max())
    else:
        x0, x1 = int(cols.min()), int(cols.max())
    pad = max(2, w // 250)
    return (max(0, x0 - pad), max(0, y0 - pad), min(w - 1, x1 + pad), min(h - 1, y1 + pad))


def detect_card_bbox(img):
    a = np.asarray(img.convert("RGB")).astype(int)
    h, w = a.shape[:2]
    bg = _bg_color(a)
    bb = _bbox_from_mask(np.abs(a - bg).sum(2) > 45, w, h)
    if bb is None or (bb[2] - bb[0]) * (bb[3] - bb[1]) > 0.82 * w * h:
        lum = (a * [0.299, 0.587, 0.114]).sum(2)
        thr = max(140, np.median(lum) + 25)
        bb2 = _bbox_from_mask(lum > thr, w, h)
        if bb2 and (bb2[2] - bb2[0]) * (bb2[3] - bb2[1]) < 0.82 * w * h:
            return bb2
    return bb if bb else (0, 0, w - 1, h - 1)


def compose(src):
    src = src.convert("RGB")
    w, h = src.size
    x0, y0, x1, y1 = detect_card_bbox(src)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    side = min(w, h)
    left = min(max(cx - side // 2, 0), w - side)
    top = min(max(cy - side // 2, 0), h - side)
    return src.crop((left, top, left + side, top + side))


def _kw(x):
    stop = {"pokemon", "card", "game", "korean", "korea", "ver", "sealed", "new", "the", "of", "and", "tcg", "official"}
    return set(re.findall(r"[a-z0-9]+", (x or "").lower())) - stop


async def _fetch_live_titles(ec):
    import xml.etree.ElementTree as ET
    import httpx

    ns = {"e": "urn:ebay:apis:eBLBaseComponents"}
    token = await ec._get_access_token()
    headers = {
        "X-EBAY-API-CALL-NAME": "GetMyeBaySelling",
        "X-EBAY-API-SITEID": "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "1349",
        "X-EBAY-API-IAF-TOKEN": token,
        "Content-Type": "text/xml",
    }
    titles = []
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
        titles += [(it.findtext("e:Title", "", ns) or "") for it in root.findall(".//e:ActiveList/e:ItemArray/e:Item", ns)]
        total = root.findtext(".//e:ActiveList/e:PaginationResult/e:TotalNumberOfPages", "1", ns)
        if page >= int(total or 1):
            break
        page += 1
    return titles


async def main():
    import httpx

    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.image.service import ImageTransformService
    from backend.domain.samba.proxy.ebay import EbayClient
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from backend.domain.samba.shipment.service import calc_market_price
    from sqlalchemy import text as t
    from sqlmodel import select

    tok = current_tenant_id.set(TENANT)
    ok = fail = 0
    try:
        async with get_write_session() as s0:
            acc = (
                (await s0.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV)))
                .scalars()
                .first()
            )
            addf = acc.additional_fields or {}
            _pr, _mp = (
                await s0.execute(t("SELECT pricing,market_policies FROM samba_policy WHERE id=:i"), {"i": POLICY})
            ).first()
            _pr = _pr if isinstance(_pr, dict) else json.loads(_pr or "{}")
            _mp = _mp if isinstance(_mp, dict) else json.loads(_mp or "{}")

        ec = EbayClient(
            app_id=addf.get("clientId") or acc.api_key,
            dev_id=addf.get("devId", ""),
            cert_id=addf.get("clientSecret") or acc.api_secret,
            refresh_token=addf.get("oauthToken") or acc.oauth_refresh_token,
        )
        live_titles = await _fetch_live_titles(ec)

        async with httpx.AsyncClient(timeout=40, headers=H) as c:
            for it in ITEMS:
                bpid, name, name_en, cost = it["pid"], it["name"], it["name_en"], float(it["cost"])
                k = _kw(name_en)
                dup = False
                for lt in live_titles:
                    lk = _kw(lt)
                    if k and lk and len(k & lk) / len(k | lk) >= 0.55:
                        print(f"[{bpid}] {name_en} !! 라이브중복 '{lt[:50]}' skip")
                        dup = True
                        break
                if dup:
                    fail += 1
                    continue
                try:
                    async with get_write_session() as s:
                        acc2 = (
                            (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV)))
                            .scalars()
                            .first()
                        )
                        dupdb = await s.execute(
                            t(
                                "SELECT id FROM samba_collected_product WHERE name_en=:n "
                                "AND registered_accounts::text LIKE :a LIMIT 1"
                            ),
                            {"n": name_en, "a": f"%{KV}%"},
                        )
                        if dupdb.first():
                            print(f"[{bpid}] {name_en} !! DB중복 skip")
                            fail += 1
                            continue

                        img_url = f"https://media.bunjang.co.kr/product/{bpid}_1_w856.jpg"
                        raw = (await c.get(img_url)).content
                        out = compose(Image.open(io.BytesIO(raw)))
                        buf = io.BytesIO()
                        out.save(buf, "JPEG", quality=92)
                        svc = ImageTransformService(s)
                        url = await svc._save_image(buf.getvalue(), img_url)

                        sale = float(calc_market_price(cost, _pr, "ebay", _mp) or cost)
                        p = SambaCollectedProduct(
                            source_site="BUNJANG",
                            name=name,
                            name_en=name_en,
                            original_price=cost,
                            sale_price=sale,
                            cost=cost,
                            status="active",
                            sale_status="in_stock",
                            source_url=f"https://m.bunjang.co.kr/products/{bpid}",
                            site_product_id=bpid,
                            images=[url],
                            applied_policy_id=POLICY,
                            tenant_id=TENANT,
                            registered_accounts=[],
                            stock_quantities={KV: 1},
                        )
                        s.add(p)
                        await s.flush()
                        pid = p.id
                        res = await dispatch_to_market(
                            s, "ebay", p.model_dump(), category_id=CAT_SINGLE, account=acc, existing_product_no=""
                        )
                        if res.get("success"):
                            lid = res.get("data", {}).get("listingId") or res.get("product_no")
                            p.registered_accounts = [KV]
                            p.market_product_nos = {KV: lid}
                            s.add(p)
                            await s.commit()
                            live_titles.append(name_en)
                            print(f"[{bpid}] {name_en} OK product={pid} listing={lid}")
                            ok += 1
                        else:
                            await s.rollback()
                            print(f"[{bpid}] {name_en} FAIL {res.get('message','')[:80]}")
                            fail += 1
                except Exception as e:
                    print(f"[{bpid}] ERR {e}")
                    fail += 1
    finally:
        current_tenant_id.reset(tok)
    print(f"\n=== 등록 완료 {ok} / 스킵·실패 {fail} / 총 {len(ITEMS)} ===")


if __name__ == "__main__":
    asyncio.run(main())
