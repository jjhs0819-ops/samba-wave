"""오매칭(교환글 5,000원) 긴급수정: 진짜 SELLING 매물로 재교체 [컨테이너, 수수료0]."""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from scipy import ndimage  # noqa: E402

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
TARGET = "cp_01KYY9SA58GCE55WRVVG2Q1DA1"
NEW_PID = "423269244"  # "메가팬텀 sar" 450,000원 (판/교 아님, plain SELLING)
NEW_COST = 450000.0
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

    tok = current_tenant_id.set(TENANT)
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
            # 진짜 SELLING 재확인
            offs = await ec.get_offers_by_sku(TARGET)
            before = offs[0].get("listing", {}).get("listingId") if offs else None
            cat = offs[0].get("categoryId", "") if offs else "183454"

            img_url = f"https://media.bunjang.co.kr/product/{NEW_PID}_1_w856.jpg"
            async with httpx.AsyncClient(timeout=40, headers=H) as c:
                raw = (await c.get(img_url)).content
            out = compose(Image.open(io.BytesIO(raw)))
            buf = io.BytesIO()
            out.save(buf, "JPEG", quality=92)
            svc = ImageTransformService(s)
            url = await svc._save_image(buf.getvalue(), img_url)

            p = (
                (await s.execute(select(SambaCollectedProduct).where(SambaCollectedProduct.id == TARGET)))
                .scalars()
                .first()
            )
            print("수정전 cost:", p.cost, "source:", p.source_url)
            p.source_url = f"https://m.bunjang.co.kr/products/{NEW_PID}"
            p.site_product_id = NEW_PID
            p.cost = NEW_COST
            p.sale_price = NEW_COST
            p.original_price = NEW_COST
            p.images = [url]
            p.sale_status = "in_stock"
            d = dict(p.stock_quantities or {})
            d[KV] = 1
            p.stock_quantities = d
            s.add(p)
            await s.flush()

            res = await dispatch_to_market(
                s, "ebay", p.model_dump(), category_id=cat, account=acc, existing_product_no=before
            )
            await s.commit()
            print("dispatch:", res.get("success"), res.get("message", "")[:100])

            offs2 = await ec.get_offers_by_sku(TARGET)
            after = offs2[0]
            print(
                "after price:", after.get("pricingSummary", {}).get("price", {}),
                "qty:", after.get("availableQuantity"),
                "status:", after.get("status"),
            )
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
