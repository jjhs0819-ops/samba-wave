"""candidates.json 일괄 적용 [컨테이너 실행]. 품절 소스 -> 새 번장 pid로 revise(수수료0).

실행:
  docker cp candidates.json local-samba-api-1:/tmp/candidates.json
  docker cp _cyc_apply.py local-samba-api-1:/tmp/_cyc_apply.py
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/_cyc_apply.py
"""
import asyncio
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from scipy import ndimage  # noqa: E402

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.bunjang.co.kr/"}


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
    from sqlmodel import select

    with open("/tmp/candidates.json", "r", encoding="utf-8") as f:
        cands = json.load(f)

    tok = current_tenant_id.set(TENANT)
    ok, fail = 0, 0
    try:
        async with get_write_session() as s:
            acc = (
                (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.id == KV)))
                .scalars()
                .first()
            )
            addf = acc.additional_fields or {}
            ec = EbayClient(
                app_id=addf.get("clientId") or acc.api_key,
                dev_id=addf.get("devId", ""),
                cert_id=addf.get("clientSecret") or acc.api_secret,
                refresh_token=addf.get("oauthToken") or acc.oauth_refresh_token,
            )
            svc = ImageTransformService(s)
            async with httpx.AsyncClient(timeout=40, headers=H) as c:
                for cand in cands:
                    pid = cand["collected_id"]
                    new_pid = cand["new_pid"]
                    new_cost = float(cand.get("new_price") or 0)
                    try:
                        offs = await ec.get_offers_by_sku(pid)
                        if not offs:
                            print(f"[{pid}] !! offer 없음, skip")
                            fail += 1
                            continue
                        o = offs[0]
                        before = o.get("listing", {}).get("listingId")
                        cat = o.get("categoryId", "")
                        if o.get("status") != "PUBLISHED":
                            print(f"[{pid}] !! status={o.get('status')}, skip(재게시=수수료)")
                            fail += 1
                            continue

                        img_url = f"https://media.bunjang.co.kr/product/{new_pid}_1_w856.jpg"
                        raw = (await c.get(img_url)).content
                        out = compose(Image.open(io.BytesIO(raw)))
                        buf = io.BytesIO()
                        out.save(buf, "JPEG", quality=92)
                        url = await svc._save_image(buf.getvalue(), img_url)

                        p = (
                            (await s.execute(select(SambaCollectedProduct).where(SambaCollectedProduct.id == pid)))
                            .scalars()
                            .first()
                        )
                        p.source_url = f"https://m.bunjang.co.kr/products/{new_pid}"
                        p.site_product_id = new_pid
                        p.cost = new_cost
                        p.sale_price = new_cost
                        p.original_price = new_cost
                        p.images = [url]
                        p.sale_status = "in_stock"
                        s.add(p)
                        await s.flush()

                        res = await dispatch_to_market(
                            s, "ebay", p.model_dump(), category_id=cat, account=acc, existing_product_no=before
                        )
                        await s.commit()

                        offs2 = await ec.get_offers_by_sku(pid)
                        after = offs2[0].get("listing", {}).get("listingId") if offs2 else None
                        tag = "revise=수수료0" if after == before else "★새리스팅=수수료!"
                        print(f"[{pid}] {cand['old_name'][:20]} -> {new_pid} OK ({tag})")
                        ok += 1
                    except Exception as e:
                        await s.rollback()
                        print(f"[{pid}] !! 실패: {e}")
                        fail += 1
    finally:
        current_tenant_id.reset(tok)

    print(f"\n=== 완료 {ok} / 실패 {fail} ===")


if __name__ == "__main__":
    asyncio.run(main())
