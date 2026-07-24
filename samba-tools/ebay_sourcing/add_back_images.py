"""기존 eBay 리스팅에 번장 원본 사진(뒷면 등)을 추가이미지로 보충 [컨테이너 실행].

배경: 대표 1장(포스트잇 합성)만 올려서 "뒷면 보여달라"는 문의가 반복된다(2026-07-24).
      번장 상세의 전체 사진(imageCount 장)을 대표 뒤에 추가한다.

규칙:
  - 1번(대표) = 기존 대표 그대로(포스트잇 합성본) 유지
  - 2번~N번  = 번장 원본 사진(뒷면 포함), R2 미러 후 추가
  - 이미 여러 장이면 건너뜀(중복 방지)
  - eBay 사진 최대 24장

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 \
      /tmp/add_back_images.py [--dry] [--limit N] [--only <sku>]
"""

import asyncio
import io
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"  # k-tcg_vault 전용
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.bunjang.co.kr/"}


def bunjang_urls(product: dict) -> list:
    tmpl = str(product.get("imageUrl") or "")
    cnt = int(product.get("imageCount") or 1)
    pid = product.get("pid") or ""
    if cnt <= 1:
        return []
    urls = []
    for i in range(2, cnt + 1):  # 2번부터(1번=대표는 포스트잇 합성본 유지)
        u = tmpl.replace("{cnt}", str(i)).replace("{res}", "856")
        if "{" in u or not tmpl:
            u = f"https://media.bunjang.co.kr/product/{pid}_{i}_w856.jpg"
        urls.append(u)
    return urls


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.image.service import ImageTransformService
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlalchemy import text as t
    from sqlmodel import select

    dry = "--dry" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 999
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None

    tok = current_tenant_id.set(TENANT)
    ok = skip = fail = 0
    try:
        async with get_write_session() as s:
            acc = (await s.execute(
                select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()
            q = t("""
                SELECT id, name_en, site_product_id, images, market_product_nos, applied_policy_id
                FROM samba_collected_product
                WHERE tenant_id = :tn AND source_site = 'BUNJANG'
                  AND registered_accounts @> CAST(:kv AS jsonb)
                ORDER BY created_at DESC
            """)
            rows = (await s.execute(q, {"tn": TENANT, "kv": f'["{KV}"]'})).all()
            if only:
                rows = [r for r in rows if r[0] == only]
            print(f"대상 {len(rows)}건")

            async with httpx.AsyncClient(timeout=40, headers=H) as c:
                for pid, en, bpid, imgs, nos, pol in rows[:limit]:
                    nm = (en or "")[:38]
                    if not (nos or {}).get(KV) or not bpid:
                        continue
                    if imgs and len(imgs) >= 2:
                        skip += 1
                        continue  # 이미 여러 장
                    try:
                        d = (await c.get(
                            f"https://api.bunjang.co.kr/api/pms/v1/products/{bpid}/detail/web"
                        )).json().get("data", {}).get("product", {})
                    except Exception as e:
                        print(f"  {nm} 상세조회 실패 {str(e)[:40]}")
                        fail += 1
                        continue
                    d["pid"] = bpid
                    extra = bunjang_urls(d)
                    if not extra:
                        skip += 1
                        continue
                    print(f"{'DRY' if dry else 'RUN'} {nm} | 추가 {len(extra)}장")
                    if dry:
                        continue
                    p = (await s.execute(select(SambaCollectedProduct).where(
                        SambaCollectedProduct.id == pid))).scalars().first()
                    svc = ImageTransformService(s)
                    new_imgs = list(p.images or [])  # 대표 유지
                    for u in extra[:23 - len(new_imgs)]:
                        try:
                            raw = (await c.get(u)).content
                            if len(raw) < 3000:
                                continue
                            new_imgs.append(await svc._save_image(raw, u))
                        except Exception:
                            pass
                    if len(new_imgs) <= len(p.images or []):
                        skip += 1
                        continue
                    p.images = new_imgs
                    s.add(p)
                    await s.commit()
                    res = await dispatch_to_market(
                        s, "ebay", p.model_dump(), category_id="183454",
                        account=acc, existing_product_no=(p.market_product_nos or {}).get(KV, ""))
                    if res.get("success"):
                        ok += 1
                        print(f"   보충완료 총 {len(new_imgs)}장")
                    else:
                        fail += 1
                        print(f"   eBay실패 {str(res.get('message'))[:60]}")
            print(f"\n완료: 보충 {ok} / 건너뜀 {skip} / 실패 {fail}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
