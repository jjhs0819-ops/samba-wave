"""KREAM 카탈로그 → eBay 대량등록 [컨테이너 실행].

절차(상품 1개당):
  1) KREAM 공식 API로 실시간 재고/가격 재확인
  2) 낱장카드 게이트: 옵션에 등급(Ungraded/PSA/BRG) 있어야 통과 (박스·팩·굿즈 배제)
  3) 포스트잇 합성사진 생성 (레퍼런스 1장 편집 방식)
  4) 합성사진으로 eBay 등록

[중요] 세션은 반드시 **상품 1건당 새로 연다**.
하나의 세션을 루프 전체에서 재사용하면 rollback 한 번에 세션이 오염되어
이후 전 건이 `greenlet_spawn has not been called` 로 연쇄 실패한다(2026-08-17 사고).

실행:
  python3 kream_batch100.py <limit> [--dry] [--start N]
"""

import asyncio
import base64
import io
import json
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
CARD_POLICY = "pol_01KXD2K5JE2HHR53GZ1NGV0PGV"  # 이베이_카드 ($9.90 배송)
CATEGORY = "183454"  # TCG 싱글카드
REF = "/tmp/reference_postit_true.jpg"
GEMINI_MODEL = "gemini-3.1-flash-image"
PROMPT = (
    "첫번째 사진에서 카드만 두번째 카드로 바꿔줘. "
    "나머지(책상 질감, 포스트잇 위치와 글씨, 조명, 그림자, 카드 각도와 위치)는 첫번째 사진 그대로 유지해."
)

GRADE_RE = re.compile(r"ungraded|psa|brg|bgs|cgc", re.I)
# 제목 기반 밀봉/굿즈 배제 (2차 방어선)
BAD_TITLE_RE = re.compile(
    r"booster|\bbox\b|\bpack\b|elite\s*trainer|\betb\b|\bkit\b|\bset\b|spinner|"
    r"\btin\b|\bbundle\b|\bcase\b|deck|starter|미개봉|부스터|박스|팩(?!\w)|세트|덱",
    re.I,
)


def _norm_part(raw_or_path):
    from PIL import Image, ImageOps

    im = Image.open(io.BytesIO(raw_or_path) if isinstance(raw_or_path, bytes) else raw_or_path)
    im = ImageOps.exif_transpose(im)
    if im.mode != "RGB":
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=95)
    return {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}


async def make_photo(client, key, card_bytes):
    """레퍼런스 사진에서 카드만 교체한 합성사진 생성. 실패 시 None."""
    body = {
        "contents": [{"role": "user", "parts": [_norm_part(REF), _norm_part(card_bytes), {"text": PROMPT}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}"
    r = await client.post(url, json=body, timeout=180)
    if r.status_code != 200:
        return None
    for part in r.json().get("candidates", [{}])[0].get("content", {}).get("parts", []):
        if "inlineData" in part:
            return base64.b64decode(part["inlineData"]["data"])
    return None


async def kream_get(kcli, pid, tries=4):
    """크림 상품조회 — 레이트리밋(ReadTimeout) 대비 백오프 재시도."""
    delay = 5
    for i in range(tries):
        try:
            return await kcli.get_product(int(pid))
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"  ..재시도 {pid} ({type(e).__name__}) {delay}s 대기", flush=True)
            await asyncio.sleep(delay)
            delay *= 2
    return 0, {}


async def load_config():
    """크림 인증/제미나이키/정책 — 별도 세션에서 1회만 읽고 값으로 반환."""
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.image.service import ImageTransformService
    from sqlalchemy import text as t
    from sqlmodel import select

    async with get_write_session() as s:
        kacc = (
            (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.market_type == "kream")))
            .scalars()
            .first()
        )
        ext = kacc.additional_fields if isinstance(kacc.additional_fields, dict) else {}
        kream_creds = (
            str(ext.get("apiService") or ""),
            str(ext.get("apiKey") or kacc.api_key or ""),
            str(ext.get("apiSecret") or kacc.api_secret or ""),
        )
        gkey, _ = await ImageTransformService(s)._get_gemini_config()
        _pr, _mp = (
            await s.execute(t("SELECT pricing,market_policies FROM samba_policy WHERE id=:i"), {"i": CARD_POLICY})
        ).first()
        _pr = _pr if isinstance(_pr, dict) else json.loads(_pr or "{}")
        _mp = _mp if isinstance(_mp, dict) else json.loads(_mp or "{}")
        done = {
            r[0]
            for r in (
                await s.execute(
                    t(
                        "SELECT site_product_id FROM samba_collected_product "
                        "WHERE source_site='KREAM' AND registered_accounts::text LIKE :a"
                    ),
                    {"a": f"%{KV}%"},
                )
            ).all()
        }
    return kream_creds, gkey, _pr, _mp, done


async def register_one(cand, name_en, name_ko, cost, photo_bytes, pricing, market_pol):
    """상품 1건 등록 — 전용 세션 사용(오염 격리)."""
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.image.service import ImageTransformService
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from backend.domain.samba.shipment.service import calc_market_price
    from sqlalchemy import text as t
    from sqlmodel import select

    pid = cand["product_id"]
    async with get_write_session() as s:
        svc = ImageTransformService(s)
        url = await svc._save_image(photo_bytes, f"{pid}_postit.jpg")

        sale = float(calc_market_price(cost, pricing, "ebay", market_pol) or cost)
        existing = (
            await s.execute(
                t("SELECT id FROM samba_collected_product WHERE source_site='KREAM' AND site_product_id=:p"),
                {"p": pid},
            )
        ).first()
        if existing:
            p = (
                (await s.execute(select(SambaCollectedProduct).where(SambaCollectedProduct.id == existing[0])))
                .scalars()
                .first()
            )
        else:
            p = SambaCollectedProduct(
                source_site="KREAM",
                tenant_id=TENANT,
                site_product_id=str(pid),
                source_url=f"https://kream.co.kr/products/{pid}",
                registered_accounts=[],
            )
        p.name = name_ko
        p.name_en = name_en
        p.original_price = cost
        p.sale_price = sale
        p.cost = cost
        p.status = "active"
        p.sale_status = "in_stock"
        p.images = [url]
        p.applied_policy_id = CARD_POLICY
        p.style_code = cand["sku"]
        p.stock_quantities = {KV: 1}
        s.add(p)
        await s.flush()

        acc = (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()
        res = await dispatch_to_market(
            s, "ebay", p.model_dump(), category_id=CATEGORY, account=acc, existing_product_no=""
        )
        if res.get("success"):
            lid = res.get("data", {}).get("listingId") or res.get("product_no")
            p.registered_accounts = [KV]
            p.market_product_nos = {KV: lid}
            s.add(p)
            await s.commit()
            return True, lid
        await s.rollback()
        return False, str(res.get("message"))[:90]


async def main():
    import httpx

    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.domain.samba.proxy.kream import KreamPartnerClient

    limit = int(sys.argv[1])
    dry = "--dry" in sys.argv
    start = int(sys.argv[sys.argv.index("--start") + 1]) if "--start" in sys.argv else 0

    with open("/tmp/pick100.json", encoding="utf-8") as f:
        cands = json.load(f)[start:]

    tok = current_tenant_id.set(TENANT)
    ok = skip = fail = 0
    try:
        kream_creds, gkey, pricing, market_pol, done = await load_config()
        kcli = KreamPartnerClient(*kream_creds)
        print(f"이미 등록됨(건너뜀 대상): {len(done)}건", flush=True)

        async with httpx.AsyncClient(timeout=180) as http:
            for c in cands:
                if ok >= limit:
                    break
                pid = c["product_id"]
                if str(pid) in done:
                    continue  # 이미 등록됨 — API 호출 없이 즉시 통과
                try:
                    await asyncio.sleep(2)  # 크림 API 레이트리밋 회피 (요청 간 간격)
                    code, body = await kream_get(kcli, pid)
                    if code != 200:
                        print(f"SKIP {pid} KREAM조회실패 {code}", flush=True)
                        skip += 1
                        continue
                    name_en = body.get("name") or ""
                    name_ko = body.get("translated_name") or name_en

                    if BAD_TITLE_RE.search(f"{name_en} {name_ko}"):
                        print(f"SKIP {pid} 밀봉/굿즈제목: {name_en[:45]}", flush=True)
                        skip += 1
                        continue

                    opts = body.get("options") or []
                    if not any(GRADE_RE.search(str(o.get("name_display") or "")) for o in opts):
                        print(f"SKIP {pid} 등급옵션없음(카드아님): {name_en[:45]}", flush=True)
                        skip += 1
                        continue

                    ask = None
                    fast = False
                    for o in opts:
                        if not GRADE_RE.search(str(o.get("name_display") or "")):
                            continue
                        n = o.get("lowest_normal_price")
                        h = o.get("lowest_100_price")
                        if n:
                            ask, fast = n, False
                            break
                        if h and ask is None:
                            ask, fast = h, True
                    if not ask:
                        print(f"SKIP {pid} 재고없음: {name_en[:45]}", flush=True)
                        skip += 1
                        continue

                    cost = float(ask) + (int(ask * 0.033) // 10) * 10 + (5000 if fast else 3000)
                    if cost > 200000:
                        print(f"SKIP {pid} 원가초과 {cost:,.0f}", flush=True)
                        skip += 1
                        continue

                    img_url = (body.get("main_images") or [None])[0]
                    if not img_url:
                        print(f"SKIP {pid} 이미지없음", flush=True)
                        skip += 1
                        continue

                    if dry:
                        print(f"DRY {pid} | {c['sku']:18s} | 원가{cost:>8,.0f} | {name_en[:50]}", flush=True)
                        ok += 1
                        continue

                    card_bytes = (await http.get(img_url, headers={"User-Agent": "Mozilla/5.0"})).content
                    photo = await make_photo(http, gkey, card_bytes)
                    if not photo:
                        print(f"FAIL {pid} 사진생성실패", flush=True)
                        fail += 1
                        continue

                    good, info = await register_one(c, name_en, name_ko, cost, photo, pricing, market_pol)
                    if good:
                        ok += 1
                        print(
                            f"OK[{ok}] {pid} | {c['sku']:18s} | 원가{cost:>8,.0f} | listing={info} | {name_en[:42]}",
                            flush=True,
                        )
                    else:
                        fail += 1
                        print(f"FAIL {pid} 등록실패: {info}", flush=True)
                except Exception as e:
                    fail += 1
                    print(f"ERR {pid} {type(e).__name__}: {str(e)[:120]}", flush=True)

        print(f"\n=== 완료: 성공 {ok} / 건너뜀 {skip} / 실패 {fail} ===", flush=True)
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
