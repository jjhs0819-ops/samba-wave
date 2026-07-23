"""tcg-vault 포스트잇 사진 일괄 교체 [컨테이너 실행].

배경: KV(k-tcg_vault) 리스팅인데 사진에 `tcg_authenticore`(다른 계정) 포스트잇이
박혀 있는 건이 36건 나왔다. 소싱처 원본 사진에서 다시 합성해 교체한다.

절차: 소싱처 원본 이미지 → postit_real 합성(비율 검수 재생성) → 여백 크롭 →
      대표이미지 교체 → eBay 리스팅 수정.

실행:
  docker cp samba-tools/ebay_sourcing/{postit_real,postit_batch}.py local-samba-api-1:/tmp/
  docker cp samba-tools/ebay_sourcing/assets/postit_small.png local-samba-api-1:/tmp/
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/postit_batch.py [--dry] [--limit N]
"""

import asyncio
import base64
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

# postit_real.py 의 PROMPT / note_ratio / 설정을 그대로 재사용 (규칙 이원화 방지)
_head = open("/tmp/postit_real.py", encoding="utf-8").read().split("async def main")[0]
# postit_real 의 stdout 재감싸기를 그대로 실행하면 GC 때 stdout 이 닫혀 출력이 죽는다
_head = "\n".join(x for x in _head.splitlines() if "sys.stdout = " not in x)
_g: dict = {}
exec(_head, _g)
PROMPT, note_ratio = _g["PROMPT"], _g["note_ratio"]
POSTIT, MAX_TRY, MAX_RATIO = _g["POSTIT"], _g["MAX_TRY"], _g["MAX_RATIO"]

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"  # k-tcg_vault 전용. 다른 계정 금지
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.bunjang.co.kr/"}


def crop_frame(img_bytes: bytes) -> bytes:
    """Gemini 가 캔버스를 가로로 넓혀 내보내므로 상품+포스트잇 기준으로 다시 잘라낸다.

    [중요] 예전엔 상단 채도만 보고 잘랐는데, 배경이 화려한 사진(천·포스터 위 촬영)에서는
    배경 전체가 잡혀 크롭이 안 먹고 파노라마처럼 남았다(2026-07-23).
    카드 열 + 포스트잇 열을 함께 쓰고, 결과가 지나치게 가로로 길면 정사각에 가깝게 맞춘다.
    """
    import numpy as np
    from PIL import Image

    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    a = np.asarray(im).astype(int)
    h, w, _ = a.shape
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]

    # 포스트잇: 하단 40% 에서 세로로 꽉 찬 노란 열
    band = a[int(h * 0.6):]
    br, bg, bb = band[:, :, 0], band[:, :, 1], band[:, :, 2]
    yl = (br > 150) & (bg > 140) & (bb < br - 20) & (bb < bg - 15)
    ncols = np.nonzero(yl.sum(axis=0) > band.shape[0] * 0.35)[0]

    # 상품: 상단 60% 에서 채도 있는 열(노란 화소 제외)
    note_px = (r > 150) & (g > 140) & (b < r - 20) & (b < g - 15)
    sat = a.max(axis=2) - a.min(axis=2)
    top = (sat[: int(h * 0.6)] > 40) & ~note_px[: int(h * 0.6)]
    ccols = np.nonzero(top.sum(axis=0) > max(8, int(h * 0.03)))[0]

    # [중요] 포스트잇은 항상 상품 바로 아래 가운데 놓이므로 그 중심이 가장 믿을 만한 기준이다.
    # 배경이 화려하면 채도 기반 상품 검출이 배경까지 잡아 크롭이 엉뚱한 곳으로 간다.
    if len(ncols):
        cx = int((ncols.min() + ncols.max()) // 2)
        half = int(max((ncols.max() - ncols.min()) * 1.5, h * 0.42))
    elif len(ccols):
        cx = int((ccols.min() + ccols.max()) // 2)
        half = int(max((ccols.max() - ccols.min()) * 0.8, h * 0.42))
    else:
        return img_bytes
    half = min(half, int(h * 0.5))
    l, rr = max(0, cx - half), min(w, cx + half)
    # 포스트잇이 잘리면 "합성 실패"처럼 보인다 → 노트 전체가 반드시 들어오게 경계를 넓힌다
    if len(ncols):
        pad = int(w * 0.02)
        l = min(l, max(0, int(ncols.min()) - pad))
        rr = max(rr, min(w, int(ncols.max()) + pad))
    # 상품(카드)도 잘리지 않게: 검출된 상품 열이 노트 폭의 3배 이내면 함께 포함
    if len(ccols) and (ccols.max() - ccols.min()) < w * 0.8:
        l = min(l, max(0, int(ccols.min()) - int(w * 0.02)))
        rr = max(rr, min(w, int(ccols.max()) + int(w * 0.02)))
    buf = io.BytesIO()
    im.crop((l, 0, rr, h)).save(buf, "JPEG", quality=95)
    return buf.getvalue()


async def gen(client, url, key, model, product_bytes, note_bytes):
    """비율 기준 통과할 때까지 재생성. 통과 못 하면 가장 작은 것을 쓴다."""
    body = {
        "contents": [{"parts": [
            {"text": PROMPT},
            {"inline_data": {"mime_type": "image/jpeg",
                             "data": base64.b64encode(product_bytes).decode("ascii")}},
            {"inline_data": {"mime_type": "image/png",
                             "data": base64.b64encode(note_bytes).decode("ascii")}},
        ]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    best, best_ratio = None, 99.0
    for tri in range(MAX_TRY):
        r = await client.post(url, json=body, headers={"Content-Type": "application/json"})
        if r.status_code == 429:
            await asyncio.sleep(30 * (tri + 1))
            continue
        r.raise_for_status()
        out = next((base64.b64decode(p["inlineData"]["data"])
                    for p in r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    if "inlineData" in p), None)
        if not out:
            continue
        ratio = note_ratio(out)
        if 0 < ratio < best_ratio:
            best, best_ratio = out, ratio
        if 0 < ratio <= MAX_RATIO:
            break
    return best, best_ratio


async def main():
    import httpx

    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.image.service import ImageTransformService
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlmodel import select

    dry = "--dry" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 999
    rows = [x for x in json.load(open("/tmp/srcchk.json", encoding="utf-8"))
            if x.get("id") and x.get("site") == "BUNJANG" and x.get("spid")]
    note = open(POSTIT, "rb").read()

    tok = current_tenant_id.set(TENANT)
    ok = fail = 0
    try:
        async with get_write_session() as s:
            key, model = await ImageTransformService(s)._get_gemini_config()
            gurl = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model}:generateContent?key={key}")
            acc = (await s.execute(
                select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()

            async with httpx.AsyncClient(timeout=180) as c:
                for i, row in enumerate(rows[:limit], 1):
                    name = (row.get("name") or "")[:38]
                    src = f"https://media.bunjang.co.kr/product/{row['spid']}_1_w856.jpg"
                    try:
                        pb = (await c.get(src, headers=H)).content
                        if len(pb) < 5000:
                            print(f"{i:>2}. SKIP(원본 없음) {name}")
                            continue
                        if dry:
                            print(f"{i:>2}. DRY {name} ← {src}")
                            continue
                        img, ratio = await gen(c, gurl, key, model, pb, note)
                        if not img:
                            print(f"{i:>2}. 실패(생성) {name}")
                            fail += 1
                            continue
                        img = crop_frame(img)

                        p = (await s.execute(select(SambaCollectedProduct).where(
                            SambaCollectedProduct.id == row["id"]))).scalars().first()
                        url = await ImageTransformService(s)._save_image(img, src)
                        p.images = [url] + [x for x in (p.images or []) if x != url][1:]
                        s.add(p)
                        await s.commit()
                        res = await dispatch_to_market(
                            s, "ebay", p.model_dump(), category_id="183454",
                            account=acc, existing_product_no=(p.market_product_nos or {}).get(KV, ""))
                        if res.get("success"):
                            ok += 1
                            print(f"{i:>2}. 교체완료 비율{ratio:.2f} {name}")
                        else:
                            fail += 1
                            print(f"{i:>2}. eBay실패 {name} — {str(res.get('message'))[:60]}")
                    except Exception as e:  # 한 건 실패로 전체가 멈추지 않게
                        fail += 1
                        print(f"{i:>2}. 예외 {name} — {str(e)[:70]}")
        print(f"완료: 성공 {ok} / 실패 {fail} / 대상 {len(rows)}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
