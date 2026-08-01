"""ATEEZ 포카 / 포켓몬 낱장 대량 신규등록 [컨테이너 실행].

입력 cands.json(batch_search.py 산출) → 각 후보:
 1) Gemini 로 영문 eBay 제목 일괄 번역
 2) postit_half 로 대표사진 합성(카드 검출 실패 시 skip)
 3) eBay 라이브 제목과 dedup(중복=계정정지 방지) 후 신규등록
 30개씩 채우면 종료. dup/실패는 로그.

실행:
  docker cp postit_half.py + batch_register.py + assets/postit_cut.png + cands.json → 컨테이너 /tmp
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/batch_register.py [--dry] [--limit 30]
"""

import asyncio
import io
import json
import re
import sys

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/tmp")

from PIL import Image  # noqa: E402
import fix_no_postit as fp  # noqa: E402  (compose_clean = 크롭만, 포스트잇/패딩 없음 · 2026-07-30 결정)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
POLICY = "pol_01KXD2K5JE2HHR53GZ1NGV0PGV"  # 이베이_카드(소형 배송)
CAT = {"ateez": "108857", "pokemon": "183454", "skz": "108857"}
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.bunjang.co.kr/"}

PROMPT = {
    "pokemon": (
        "Translate each Korean Pokemon TCG SINGLE card listing title into a concise English "
        "eBay title. Format exactly: 'Pokemon Card <CardName> <Rarity> (Korean)'. Examples of "
        "card names: Mega Charizard X ex, Mega Gengar ex, Meowth ex, Pikachu ex, Magikarp Promo, "
        "Mega Venusaur ex, Mega Zygarde. Rarity like SR/RR/SAR/UR/AR if present, else omit. "
        "Do NOT invent a quantity. Return ONLY a JSON array of strings, same order, no prose."
    ),
    "ateez": (
        "Translate each Korean ATEEZ K-pop photocard listing title into a concise English eBay "
        "title. Format: 'ATEEZ <Era/Album> Official Photocard - <Member>'. Members: Hongjoong, "
        "Seonghwa, Yunho, Yeosang, San, Mingi, Wooyoung, Jongho. Eras include Golden Hour Part.5, "
        "Golden Hour Part.4, Fanmeeting ATINY ZONE, Aniteez, Apple Music Barista. If member "
        "unknown omit the '- <Member>' part. Return ONLY a JSON array of strings, same order."
    ),
    "skz": (
        "Translate each Korean Stray Kids K-pop photocard listing title into a concise English "
        "eBay title. Format: 'Stray Kids <Era/Album> Official Photocard - <Member>'. Members: "
        "Bang Chan, Lee Know, Changbin, Hyunjin, Han, Felix, Seungmin, I.N. Eras include Rock-Star, "
        "5-STAR, MAXIDENT, ODDINARY, NOEASY, Case 143, Social Path, Holiday, THIS OR THAT, Run It. "
        "If member unknown omit the '- <Member>' part. Return ONLY a JSON array of strings, same order."
    ),
}


async def gemini_titles(svc, names, kind):
    import httpx

    (
        key,
        model,
    ) = await svc._get_gemini_config()  # gemini-2.5-flash-image = 텍스트도 정상
    numbered = "\n".join(f"{i + 1}. {n}" for i, n in enumerate(names))
    body = {"contents": [{"parts": [{"text": PROMPT[kind] + "\n\n" + numbered}]}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(url, json=body, headers={"Content-Type": "application/json"})
    txt = ""
    for p in r.json().get("candidates", [{}])[0].get("content", {}).get("parts", []):
        txt += p.get("text", "")
    m = re.search(r"\[.*\]", txt, re.S)
    arr = json.loads(m.group(0)) if m else []
    return arr + [""] * (len(names) - len(arr))


def _kw(x, stop):
    return set(re.findall(r"[a-z0-9]+", (x or "").lower())) - stop


async def fetch_live_titles(session, acc_id):
    """eBay 활성 리스팅 제목 전체(Trading GetMyeBaySelling ActiveList) — dedup 기준."""
    import xml.etree.ElementTree as ET

    import httpx
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.resolver import resolve_market_creds
    from backend.domain.samba.proxy.ebay import EbayClient
    from sqlmodel import select

    ns = {"e": "urn:ebay:apis:eBLBaseComponents"}
    acc = (
        (
            await session.execute(
                select(SambaMarketAccount).where(SambaMarketAccount.id == acc_id)
            )
        )
        .scalars()
        .first()
    )
    ax = getattr(acc, "additional_fields", None) or {}
    cr = (
        await resolve_market_creds(
            session, TENANT, market_type="ebay", store_key="store_ebay"
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
    headers = {
        "X-EBAY-API-CALL-NAME": "GetMyeBaySelling",
        "X-EBAY-API-SITEID": "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "1349",
        "X-EBAY-API-IAF-TOKEN": token,
        "Content-Type": "text/xml",
    }
    titles, page = [], 1
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
        total = root.findtext(
            ".//e:ActiveList/e:PaginationResult/e:TotalNumberOfPages", "1", ns
        )
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
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from backend.domain.samba.shipment.service import calc_market_price
    from sqlalchemy import text as t
    from sqlmodel import select

    dry = "--dry" in sys.argv
    limit = (
        int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 30
    )
    data = json.load(open("/tmp/cands.json", encoding="utf-8"))
    stop = {
        "pokemon",
        "card",
        "game",
        "korean",
        "korea",
        "ver",
        "sealed",
        "new",
        "the",
        "of",
        "and",
        "tcg",
        "official",
        "photocard",
        "ateez",
    }

    tok = current_tenant_id.set(TENANT)
    try:
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
            svc = ImageTransformService(s)
            live = await fetch_live_titles(s, KV)
            # [B] DB에 이미 있는 카드(등록/고정가/재고 보유분)도 dedup 대상에 포함.
            # eBay 리스팅이 소스품절로 종료돼 live에서 사라져도 같은 카드를 다시
            # 신규등록하면 중복=계정정지. live만 보던 게 한 달째 중복 재발 원인.
            db_titles = [
                r[0]
                for r in (
                    await s.execute(
                        t(
                            "SELECT DISTINCT name_en FROM samba_collected_product "
                            "WHERE tenant_id=:tn AND name_en IS NOT NULL AND name_en <> '' "
                            "AND (registered_accounts @> CAST(:kvj AS jsonb) "
                            "     OR price_locked = TRUE "
                            "     OR (stock_quantities->>:kv) IS NOT NULL)"
                        ),
                        {"tn": TENANT, "kvj": f'["{KV}"]', "kv": KV},
                    )
                ).all()
            ]
            live = live + [x for x in db_titles if x]
            live_kw = [_kw(x, stop) for x in live]
            print(f"dedup 기준 {len(live)}건 (eBay live + DB 등록/고정가/재고)")

            _pr, _mp = (
                await s.execute(
                    t("SELECT pricing,market_policies FROM samba_policy WHERE id=:i"),
                    {"i": POLICY},
                )
            ).first()
            _pr = _pr if isinstance(_pr, dict) else json.loads(_pr or "{}")
            _mp = _mp if isinstance(_mp, dict) else json.loads(_mp or "{}")

            only = (
                sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
            )
            for kind in ("ateez", "pokemon", "skz"):
                if only and kind != only:
                    continue
                cands = data[kind]
                names = [c["name"] for c in cands]
                titles = await gemini_titles(svc, names, kind)
                print(f"\n===== {kind.upper()} (목표 {limit}) =====")
                done = 0
                async with httpx.AsyncClient(timeout=40, headers=H) as c:
                    for cand, title in zip(cands, titles):
                        if done >= limit:
                            break
                        bpid, cost = cand["bpid"], int(cand["price"])
                        title = (title or "").strip()[:78]
                        k = _kw(title, stop)
                        # 안전: 구별 토큰 없는 제목(예 'ATEEZ Official Photocard')은
                        # dedup 우회 + 동일제목 중복등록 위험 → skip
                        if not k:
                            print(f"  skip(무구별) {title[:40]}")
                            continue
                        # dedup: 라이브 제목/이번 배치 제목과 키워드 유사
                        if any(
                            len(k & lk) / len(k | lk) >= 0.55 for lk in live_kw if lk
                        ):
                            print(f"  dup   {title[:44]}")
                            continue
                        # 이미 DB에 있는 bpid는 INSERT 시 unique 위반(uq_scp_tenant_source_product_v2)
                        # → 중복수집. 스킵(전체 배치 crash 방지).
                        _exists = (
                            await s.execute(
                                select(SambaCollectedProduct.id).where(
                                    SambaCollectedProduct.tenant_id == TENANT,
                                    SambaCollectedProduct.source_site == "BUNJANG",
                                    SambaCollectedProduct.site_product_id == bpid,
                                )
                            )
                        ).first()
                        if _exists:
                            print(f"  exists {title[:40]}")
                            continue
                        # 대표사진 합성
                        try:
                            raw = (
                                await c.get(
                                    f"https://media.bunjang.co.kr/product/{bpid}_1_w856.jpg"
                                )
                            ).content
                            out, _reason = fp.compose_clean(Image.open(io.BytesIO(raw)))
                            buf = io.BytesIO()
                            out.save(buf, "JPEG", quality=92)
                            img_bytes = buf.getvalue()
                        except Exception as e:
                            print(f"  imgX  {title[:40]} ({str(e)[:30]})")
                            continue
                        sale = float(
                            calc_market_price(float(cost), _pr, "ebay", _mp) or cost
                        )
                        print(
                            f"  {'DRY' if dry else 'REG'} {done + 1:2d} {cost:,}원→${sale:,.2f} | {title[:46]}"
                        )
                        if dry:
                            with open(
                                f"/tmp/prev_{done + 1:02d}_{bpid}.jpg", "wb"
                            ) as _pf:
                                _pf.write(img_bytes)
                            done += 1
                            live_kw.append(k)
                            continue
                        img_url = await svc._save_image(
                            img_bytes,
                            f"https://media.bunjang.co.kr/product/{bpid}_1.jpg",
                        )
                        p = SambaCollectedProduct(
                            source_site="BUNJANG",
                            name=cand["name"],
                            name_en=title,
                            original_price=cost,
                            sale_price=sale,
                            cost=cost,
                            status="active",
                            sale_status="in_stock",
                            source_url=f"https://m.bunjang.co.kr/products/{bpid}",
                            site_product_id=bpid,
                            images=[img_url],
                            applied_policy_id=POLICY,
                            tenant_id=TENANT,
                            registered_accounts=[],
                            stock_quantities={KV: 1},
                        )
                        s.add(p)
                        await s.flush()
                        res = await dispatch_to_market(
                            s,
                            "ebay",
                            p.model_dump(),
                            category_id=CAT[kind],
                            account=acc,
                            existing_product_no="",
                        )
                        if res.get("success"):
                            lid = res.get("data", {}).get("listingId") or res.get(
                                "product_no"
                            )
                            p.registered_accounts = [KV]
                            p.market_product_nos = {KV: lid}
                            s.add(p)
                            await s.commit()
                            done += 1
                            live_kw.append(k)
                            print(f"       OK listing={lid}")
                        else:
                            await s.rollback()
                            print(f"       실패 {str(res.get('message'))[:50]}")
                print(f"{kind.upper()} 등록 {done}건")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
