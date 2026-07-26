"""컬러 단색 표면에 가짜 패딩된 대표사진 재합성 [컨테이너 실행].

postit_half 의 옛 로직이 노란 종이 등 '컬러 단색' 배경을 벽으로 오판해 평면색으로
확장(합성 티)했다. 흰 벽이 아닌(near_white=False) 최근 등록분만 크롭 방식으로 재합성
후 eBay revise. 흰 벽 건은 그대로 둔다.

실행:
  docker cp postit_half.py refix_images.py + assets/postit_cut.png → /tmp
  docker exec ... /tmp/refix_images.py --dry   # 대상수 + 샘플 /tmp/refix_*.jpg 저장
  docker exec ... /tmp/refix_images.py         # 실제 revise
"""

import asyncio
import base64
import io
import sys

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/tmp")

from PIL import Image  # noqa: E402
import postit_half as ph  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.bunjang.co.kr/"}

# PIL 로 정확한 크기·위치에 놓은 포스트잇을 Gemini 가 '실물처럼' blend (오려붙인 티 제거).
# 크기·위치·카드·배경은 그대로, 노트만 자연스럽게.
REFINE = (
    "This image already has a small yellow paper note (handwritten 'tcg-vault') placed at the "
    "bottom. It currently looks digitally pasted/cut-out. Re-render ONLY that yellow note so it "
    "looks like a REAL physical paper note photographed in this exact scene: match the surrounding "
    "surface lighting, white balance and grain, soften/blend the paper edges, add a subtle "
    "realistic contact shadow under it. CRITICAL: keep the note's exact same size, position and "
    "handwritten text. Do NOT move or resize it. Do NOT change the card, the background, the "
    "framing or anything else. Output the same image, only the note blended naturally."
)


async def gemini_refine(key, model, img_bytes):
    """PIL 합성본을 Gemini 로 자연 blend. 재시도 4회(429/실패 백오프).
    끝까지 실패하면 **None** 반환 → 호출부가 스킵(컷아웃 폴백 게시 절대 금지)."""
    import asyncio
    import httpx

    body = {"contents": [{"parts": [
        {"text": REFINE},
        {"inline_data": {"mime_type": "image/jpeg",
                         "data": base64.b64encode(img_bytes).decode()}}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
           f":generateContent?key={key}")
    for attempt in range(4):
        try:
            async with httpx.AsyncClient(timeout=180) as c:
                r = await c.post(url, json=body, headers={"Content-Type": "application/json"})
            if r.status_code == 429:
                await asyncio.sleep(20 * (attempt + 1))
                continue
            for p in r.json().get("candidates", [{}])[0].get("content", {}).get("parts", []):
                if "inlineData" in p:
                    out = base64.b64decode(p["inlineData"]["data"])
                    im = Image.open(io.BytesIO(out)).convert("RGB")
                    w, h = im.size
                    if abs(w - h) > 4:
                        s = min(w, h)
                        im = im.crop(((w - s) // 2, (h - s) // 2,
                                      (w - s) // 2 + s, (h - s) // 2 + s))
                    b = io.BytesIO()
                    im.save(b, "JPEG", quality=92)
                    return b.getvalue()
            # 이미지 파트 없음 → 재시도
            await asyncio.sleep(8 * (attempt + 1))
        except Exception:
            await asyncio.sleep(8 * (attempt + 1))
    return None  # 컷아웃 폴백 금지 — 스킵


async def main():
    import httpx

    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.image.service import ImageTransformService
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlalchemy import text as tx
    from sqlmodel import select

    dry = "--dry" in sys.argv
    tok = current_tenant_id.set(TENANT)
    paper = ph.extract_paper("/tmp/postit_cut.png")
    try:
        async with get_write_session() as s:
            acc = (await s.execute(
                select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()
            svc = ImageTransformService(s)
            gkey, gmodel = await svc._get_gemini_config()
            rows = (await s.execute(tx(
                "SELECT id, site_product_id, name_en, applied_policy_id, market_product_nos->>:kv "
                "FROM samba_collected_product WHERE registered_accounts @> CAST(:kvj AS jsonb) "
                "AND source_site='BUNJANG' AND created_at > now() - interval '3 days'"),
                {"kv": KV, "kvj": f'["{KV}"]'})).all()
            print(f"검사 대상 {len(rows)}건")
            fixed = skip_white = 0
            async with httpx.AsyncClient(timeout=40, headers=H) as c:
                for pid_sku, bpid, nm, pol, lid in rows:
                    if not bpid or not lid:
                        continue
                    try:
                        raw = (await c.get(
                            f"https://media.bunjang.co.kr/product/{bpid}_1_w856.jpg")).content
                        src = Image.open(io.BytesIO(raw))
                        out = ph.compose(src, paper)  # 크롭전용, 패딩 없음 → 전량 재합성
                    except Exception as e:
                        print(f"  imgX {nm[:30]} ({str(e)[:30]})")
                        continue
                    import asyncio as _aio
                    buf = io.BytesIO()
                    out.save(buf, "JPEG", quality=94)
                    final = await gemini_refine(gkey, gmodel, buf.getvalue())
                    await _aio.sleep(1.5)  # rate-limit 회피
                    if final is None:  # Gemini 블렌드 실패 → 컷아웃 게시 금지, 스킵
                        skip_white += 1
                        print(f"  SKIP(블렌드실패, 구이미지유지) {nm[:38]}")
                        continue
                    if dry:
                        if fixed < 4:
                            open(f"/tmp/refix_{fixed}.jpg", "wb").write(final)
                        fixed += 1
                        print(f"  DRY 재합성대상 {nm[:40]}")
                        continue
                    p = (await s.execute(select(SambaCollectedProduct).where(
                        SambaCollectedProduct.id == pid_sku))).scalars().first()
                    new_url = await svc._save_image(
                        final, f"https://media.bunjang.co.kr/product/{bpid}_1.jpg")
                    p.images = [new_url] + list(p.images or [])[1:]
                    s.add(p)
                    await s.commit()
                    cat = "108857" if pol in ("pol_kpopcard_v1", "pol_kpopgoods_v1") \
                        or nm.startswith(("ATEEZ", "Stray Kids")) else "183454"
                    res = await dispatch_to_market(
                        s, "ebay", p.model_dump(), category_id=cat, account=acc,
                        existing_product_no=lid)
                    fixed += 1
                    print(f"  {'OK' if res.get('success') else '실패'} {nm[:40]}")
            print(f"\n재합성 {fixed} / 흰벽스킵 {skip_white} / 총 {len(rows)}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
