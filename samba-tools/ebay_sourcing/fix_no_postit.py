"""대표사진에서 가짜 배경 패딩 + 오려붙인 포스트잇 제거 [컨테이너 실행].

2026-07-30 사용자 결정(반복 격노 3회):
  - 배경색 패딩 / 캔버스 확장 **영구 금지** (좌우 회색·흰 띠가 합성 티)
  - 포스트잇 오려붙이기 **영구 금지** (평면 사각형이 티남)
  → 대표사진은 소싱처 원본에서 **크롭만**. 카드가 정사각에 안 들어가면 크롭도 안 하고
    원본 비율 그대로 둔다(잘림보다 원본 유지가 낫다).

절차: 불량 판정(패딩/포스트잇) → 번장 원본 재다운로드 → 크롭 → **재검증(패딩0·포스트잇0)**
      → R2 저장 → 대표이미지 교체 → eBay revise.

실행:
  docker cp samba-tools/ebay_sourcing/fix_no_postit.py local-samba-api-1:/tmp/
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/fix_no_postit.py --dry
  docker cp local-samba-api-1:/tmp/fixed_<sku6>.jpg .   # 육안검증
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/fix_no_postit.py
옵션: --limit N  --only <sku>  --skip N   (컨테이너 OOM(exit137) 방지용 배치 실행)

카테고리 함정: 우리가 정책으로 계산한 카테고리(108857 등)를 그대로 보내면 실제 리스팅
카테고리와 달라 `item specific Game is missing`(25002) 400 이 난다. 그래서 **리스팅의
현재 categoryId 를 eBay 에서 읽어 그 값으로 revise** 한다.
"""

import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from scipy import ndimage  # noqa: E402

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"  # k-tcg_vault. 다른 계정 절대 건드리지 말 것
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.bunjang.co.kr/"}


# ---------------------------------------------------------------- 판정
def is_padded(a: np.ndarray) -> bool:
    """마주보는 두 테두리 스트립이 거의 단색 + 서로 같은 색 → 가짜 캔버스 확장."""
    h, w = a.shape[:2]
    sw, sh = max(4, int(w * 0.035)), max(4, int(h * 0.035))
    for p, q in ((a[:, :sw], a[:, -sw:]), (a[:sh], a[-sh:])):
        if (
            p.reshape(-1, 3).std(0).mean() < 9
            and q.reshape(-1, 3).std(0).mean() < 9
            and np.abs(p.reshape(-1, 3).mean(0) - q.reshape(-1, 3).mean(0)).sum() < 24
        ):
            return True
    return False


def has_postit(a: np.ndarray, bbox=None) -> bool:
    """하단부의 '노란 직사각 블롭 + 내부 검은 손글씨' → 오려붙인 tcg-vault 포스트잇.

    노란 카드·포장 오탐 방지: 가로세로비 1.6~8, 채움률 0.72↑, 가로 중앙, 내부 어두운 획.
    bbox(상품 사각형)를 주면 **상품 아래쪽만** 본다 — 노란 테두리 카드(제크로무 등)를
    포스트잇으로 오판해 교정을 스킵하던 문제(2026-07-30 4건 잔존) 방지.
    """
    h, w = a.shape[:2]
    y_from = int(h * 0.55)
    if bbox:
        # 상품 하단 경계 아래만 검사(상품 자체의 노란색 제외)
        y_from = max(y_from, min(h - 1, bbox[3] + 1))
        if h - y_from < 12:
            return False
    bot = a[y_from:]
    r, g, b = bot[:, :, 0], bot[:, :, 1], bot[:, :, 2]
    yellow = (r > 175) & (g > 155) & (b < 175) & ((r - b) > 30) & ((r - g) < 60)
    yellow = ndimage.binary_closing(yellow, iterations=2)
    lbl, n = ndimage.label(yellow)
    if n == 0:
        return False
    sizes = ndimage.sum(yellow, lbl, range(1, n + 1))
    for idx in np.argsort(sizes)[::-1][:3]:
        m = lbl == (int(idx) + 1)
        if m.sum() < 0.004 * bot.size / 3:
            continue
        ys, xs = np.where(m)
        bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        ar, fill = bw / max(1, bh), m.sum() / (bw * bh)
        cx = (xs.min() + xs.max()) / 2 / w
        inner = bot[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
        if (
            1.6 <= ar <= 8
            and fill > 0.72
            and 0.25 < cx < 0.78
            and float((inner.max(2) < 110).mean()) > 0.004
        ):
            return True
    return False


# ---------------------------------------------------------------- 생성
def _bg_color(a: np.ndarray):
    """테두리 링의 최빈색 = 배경(벽)."""
    h, w = a.shape[:2]
    bt, bs = max(3, int(h * 0.04)), max(3, int(w * 0.04))
    ring = np.concatenate(
        [
            a[:bt].reshape(-1, 3),
            a[-bt:].reshape(-1, 3),
            a[:, :bs].reshape(-1, 3),
            a[:, -bs:].reshape(-1, 3),
        ]
    )
    keys, counts = np.unique((ring // 16) * 16, axis=0, return_counts=True)
    return keys[int(np.argmax(counts))].astype(float) + 8


def _bbox(m: np.ndarray, w: int, h: int):
    """마스크 최대 블롭에서 행/열 투영으로 상품 사각형만(손가락 등 좁은 돌출 제거)."""
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
    return (
        max(0, x0 - pad),
        max(0, y0 - pad),
        min(w - 1, x1 + pad),
        min(h - 1, y1 + pad),
    )


def detect_bbox(img: Image.Image):
    a = np.asarray(img.convert("RGB")).astype(int)
    h, w = a.shape[:2]
    bb = _bbox(np.abs(a - _bg_color(a)).sum(2) > 45, w, h)
    if bb is None or (bb[2] - bb[0]) * (bb[3] - bb[1]) > 0.82 * w * h:
        lum = (a * [0.299, 0.587, 0.114]).sum(2)
        bb2 = _bbox(lum > max(140, np.median(lum) + 25), w, h)
        if bb2 and (bb2[2] - bb2[0]) * (bb2[3] - bb2[1]) < 0.82 * w * h:
            return bb2
    return bb if bb else (0, 0, w - 1, h - 1)


def compose_clean(src: Image.Image) -> tuple[Image.Image, str]:
    """패딩·포스트잇 없는 대표사진. 상품이 정사각에 다 들어갈 때만 크롭, 아니면 원본 유지."""
    src = src.convert("RGB")
    w, h = src.size
    x0, y0, x1, y1 = detect_bbox(src)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    side = min(w, h)
    if bw > side or bh > side:
        return src, "원본유지(상품이 정사각보다 큼 — 잘림 방지)"
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    left = min(max(cx - side // 2, 0), w - side)
    top = min(max(cy - side // 2, 0), h - side)
    # 상품이 크롭 창을 벗어나면 창을 밀어 넣는다(얼굴/상단 잘림 방지)
    left = min(left, x0)
    left = max(left, x1 - side + 1, 0)
    top = min(top, y0)
    top = max(top, y1 - side + 1, 0)
    return src.crop((left, top, left + side, top + side)), "정사각크롭"


# ---------------------------------------------------------------- 실행
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
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    skip = int(sys.argv[sys.argv.index("--skip") + 1]) if "--skip" in sys.argv else 0

    tok = current_tenant_id.set(TENANT)
    try:
        sql = tx(
            "SELECT id, name, images, site_product_id, applied_policy_id, "
            "       market_product_nos->>CAST(:kv AS text) AS lid, style_code "
            "FROM samba_collected_product "
            "WHERE tenant_id = :tn AND market_product_nos ? CAST(:kv AS text) "
            "  AND source_site = 'BUNJANG' ORDER BY id LIMIT 5000"
        )
        async with get_write_session() as s:
            rows = [
                tuple(r) for r in (await s.execute(sql, {"tn": TENANT, "kv": KV})).all()
            ]
        if only:
            rows = [r for r in rows if r[0] == only]
        if skip:
            rows = rows[skip:]
        print(f"KV·번장 등록 {len(rows)}건 검사(skip={skip})")

        acc = None
        fixed = skip_ok = fail = 0
        seen = 0  # 이번 실행에서 훑은 건수(다음 배치 --skip 계산용)
        async with httpx.AsyncClient(timeout=45, headers=H) as c:
            async with get_write_session() as s:
                acc = (
                    (
                        await s.execute(
                            select(SambaMarketAccount).where(
                                SambaMarketAccount.id == KV
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                svc = ImageTransformService(s)
                # 리스팅의 현재 카테고리를 읽기 위한 eBay 클라이언트
                from backend.domain.samba.proxy.ebay import EbayClient

                ex = getattr(acc, "additional_fields", None) or {}
                cli = EbayClient(
                    app_id=ex.get("clientId", ""),
                    dev_id=ex.get("devId", ""),
                    cert_id=ex.get("clientSecret", ""),
                    refresh_token=ex.get("oauthToken", ""),
                )

                async def live_category(*sku_cands: str) -> str:
                    """리스팅에 실제로 박힌 categoryId. 못 읽으면 빈 문자열.

                    실사용 SKU 는 상품 id(cp_...) 인 경우가 많다(style_code 없으면 그쪽).
                    후보를 순서대로 시도한다.
                    """
                    for sk in [x for x in sku_cands if x]:
                        try:
                            offers = await cli.get_offers_by_sku(sk)
                            if offers:
                                return offers[0].get("categoryId") or ""
                        except Exception:  # noqa: BLE001
                            continue
                    return ""

                for pid, name, images, spid, pol, lid, style in rows:
                    seen += 1
                    imgs = list(images or [])
                    if not imgs or not spid:
                        continue
                    tag = pid[-6:]
                    try:
                        cur = np.asarray(
                            Image.open(
                                io.BytesIO((await c.get(imgs[0])).content)
                            ).convert("RGB")
                        ).astype(int)
                    except Exception as e:  # noqa: BLE001
                        print(f"[{tag}] 현재이미지 로드실패 {type(e).__name__}")
                        fail += 1
                        continue
                    if not (is_padded(cur) or has_postit(cur)):
                        skip_ok += 1
                        continue
                    # 번장 원본 재수집 → 크롭
                    try:
                        raw = (
                            await c.get(
                                f"https://media.bunjang.co.kr/product/{spid}_1_w856.jpg"
                            )
                        ).content
                        srcimg = Image.open(io.BytesIO(raw))
                        out, how = compose_clean(srcimg)
                        out_bbox = detect_bbox(out)
                    except Exception as e:  # noqa: BLE001
                        print(f"[{tag}] 원본수집/크롭 실패 {type(e).__name__} — 스킵")
                        fail += 1
                        continue
                    buf = io.BytesIO()
                    out.save(buf, "JPEG", quality=92)
                    chk = np.asarray(out).astype(int)
                    # 상품 바깥(하단)만 검사 — 노란 카드 자체를 포스트잇으로 오판 방지
                    bad_pad, bad_note = is_padded(chk), has_postit(chk, out_bbox)
                    if bad_pad or bad_note:
                        # 원본 자체가 단색 배경이면 패딩 판정이 뜰 수 있다. 포스트잇이면 무조건 중단.
                        if bad_note:
                            print(
                                f"[{tag}] 재생성물에 포스트잇 검출 — 중단(반영 안 함)"
                            )
                            fail += 1
                            continue
                        how += "(원본배경이 단색)"
                    open(f"/tmp/fixed_{tag}.jpg", "wb").write(buf.getvalue())
                    print(
                        f"[{tag}] {name[:32]} {how} {out.size} → /tmp/fixed_{tag}.jpg"
                    )
                    if dry:
                        fixed += 1
                        if limit and fixed >= limit:
                            break
                        continue
                    p = (
                        (
                            await s.execute(
                                select(SambaCollectedProduct).where(
                                    SambaCollectedProduct.id == pid
                                )
                            )
                        )
                        .scalars()
                        .first()
                    )
                    new_url = await svc._save_image(buf.getvalue(), imgs[0])
                    p.images = [new_url] + imgs[1:]
                    s.add(p)
                    await s.commit()
                    # 리스팅에 박힌 카테고리 우선 — 정책 계산값을 쓰면 필수 aspect 불일치로 400
                    cat = await live_category(pid, style, spid)
                    if not cat:
                        cat = (
                            "108857"
                            if pol in ("pol_kpopcard_v1", "pol_kpopgoods_v1")
                            else "183454"
                        )
                    res = await dispatch_to_market(
                        s,
                        "ebay",
                        p.model_dump(),
                        category_id=cat,
                        account=acc,
                        existing_product_no=lid,
                    )
                    ok = res.get("success")
                    print(f"    eBay revise {'OK' if ok else res.get('message')}")
                    fixed += 1 if ok else 0
                    fail += 0 if ok else 1
                    if limit and fixed >= limit:
                        break
        print(
            f"\n{'[dry] ' if dry else ''}교체 {fixed} / 정상스킵 {skip_ok} / 실패 {fail} "
            f"/ 훑음 {seen} / 총 {len(rows)}  다음배치: --skip {skip + seen}"
        )
    finally:
        current_tenant_id.reset(tok)


# 가드 필수 — 다른 스크립트가 판정 함수만 import 할 때 교체 작업이 실행되면 안 된다.
if __name__ == "__main__":
    asyncio.run(main())
