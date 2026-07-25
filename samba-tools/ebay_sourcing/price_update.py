"""번장 원문 가격 변동 → 원가·판매가 갱신 + eBay revise [컨테이너 실행].

번장 상품은 재고1이라 "업데이트" = 가격 반영 + 품절 처리다.
번장 현재가가 DB 원가와 5% 이상 다르면 원가를 현재가로 갱신하고,
정책 판매가를 재계산해 eBay 리스팅을 revise 한다.

규칙:
  - [원가 상한] MAX_COST(30만원) 이상이면 건너뛴다(고가 리스크 회피, 사용자 지정).
  - 가격만 손댄다. 재고·하자고지·사진 등 손수작업은 그대로 둔다
    (dispatch 가 기존 리스팅 재고를 유지하도록 이미 고쳐져 있음).
  - 번장이 SOLD_OUT/삭제면 여기선 손대지 않는다(품절 처리는 별도/복구루틴).

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 \
      /tmp/price_update.py [--dry] [--min-delta 0.05] [--max-cost 300000]
"""

import asyncio
import io
import json
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.bunjang.co.kr/"}


def min_fee(trade: dict) -> int:
    if (trade or {}).get("freeShipping"):
        return 0
    specs = (trade or {}).get("shippingSpecs") or {}
    fees = [int(v.get("fee") or 0) for v in specs.values() if isinstance(v, dict)]
    return min(fees) if fees else 0


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from backend.domain.samba.shipment.service import calc_market_price
    from sqlalchemy import text as t
    from sqlmodel import select

    dry = "--dry" in sys.argv
    min_delta = float(sys.argv[sys.argv.index("--min-delta") + 1]) if "--min-delta" in sys.argv else 0.05
    max_cost = float(sys.argv[sys.argv.index("--max-cost") + 1]) if "--max-cost" in sys.argv else 300000

    tok = current_tenant_id.set(TENANT)
    ok = skip = fail = 0
    try:
        async with get_write_session() as s:
            acc = (await s.execute(
                select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()
            rows = (await s.execute(t("""
                SELECT id, name_en, site_product_id, cost, applied_policy_id, market_product_nos
                FROM samba_collected_product
                WHERE tenant_id = :tn AND source_site = 'BUNJANG'
                  AND registered_accounts @> CAST(:kv AS jsonb)
                ORDER BY created_at DESC
            """), {"tn": TENANT, "kv": f'["{KV}"]'})).all()
            print(f"번장 등록분 {len(rows)}건")

            async with httpx.AsyncClient(timeout=30, headers=H) as c:
                for pid, en, bpid, dc, pol, nos in rows:
                    lid = (nos or {}).get(KV, "")
                    if not bpid or not lid:
                        continue
                    # [중요] 번장 API 는 연속 호출을 rate-limit 한다. except:continue 로
                    # 넘기면 대부분 조용히 건너뛰어 1건만 처리됐다(2026-07-25). 재시도 + 간격.
                    d = None
                    for _try in range(3):
                        try:
                            r = await c.get(
                                f"https://api.bunjang.co.kr/api/pms/v1/products/{bpid}/detail/web")
                            if r.status_code == 200:
                                d = r.json().get("data", {}).get("product", {})
                                break
                        except Exception:
                            pass
                        await asyncio.sleep(2)
                    if not d:
                        fail += 1
                        print(f"조회실패 {(en or '')[:36]}")
                        continue
                    await asyncio.sleep(0.6)
                    if d.get("saleStatus") != "SELLING":
                        continue  # 품절은 여기서 안 다룸
                    new_cost = int(d.get("price") or 0) + min_fee(d.get("trade"))
                    dc = float(dc or 0)
                    if new_cost <= 0 or dc <= 0:
                        continue
                    if abs(new_cost - dc) / dc < min_delta:
                        continue  # 변동 미미
                    nm = (en or "")[:36]
                    if new_cost >= max_cost:
                        skip += 1
                        print(f"SKIP(원가 {new_cost:,}≥{int(max_cost):,}) {nm}")
                        continue

                    _pr, _mp = (await s.execute(
                        t("SELECT pricing, market_policies FROM samba_policy WHERE id=:i"),
                        {"i": pol})).first()
                    _pr = _pr if isinstance(_pr, dict) else json.loads(_pr or "{}")
                    _mp = _mp if isinstance(_mp, dict) else json.loads(_mp or "{}")
                    sale = float(calc_market_price(float(new_cost), _pr, "ebay", _mp) or new_cost)
                    print(f"{'DRY' if dry else 'RUN'} {nm} | {int(dc):,}→{new_cost:,}원 | 판매 {int(sale):,}")
                    if dry:
                        continue
                    p = (await s.execute(select(SambaCollectedProduct).where(
                        SambaCollectedProduct.id == pid))).scalars().first()
                    p.cost = float(new_cost)
                    p.original_price = float(new_cost)
                    p.sale_price = sale
                    s.add(p)
                    await s.commit()
                    try:
                        res = await dispatch_to_market(
                            s, "ebay", p.model_dump(), category_id="183454",
                            account=acc, existing_product_no=lid)
                        if res.get("success"):
                            ok += 1
                        else:
                            fail += 1
                            print(f"   eBay실패 {str(res.get('message'))[:60]}")
                    except Exception as e:
                        fail += 1
                        print(f"   예외 {str(e)[:60]}")
            print(f"\n완료: 갱신 {ok} / 상한초과 건너뜀 {skip} / 실패 {fail}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
