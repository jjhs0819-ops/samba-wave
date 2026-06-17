"""주문이행가능(역마진/재고) 판정 dry-run — 오늘 eligible pending 건 실제 refresh 후 판정만 출력(쓰기 X).

auto_issue_check.auto_check_order_issues 와 동일 로직을 mutate 없이 재현.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlmodel import col, select

from backend.db.orm import get_read_session
from backend.domain.samba.collector.model import SambaCollectedProduct
from backend.domain.samba.collector.refresher import refresh_products_bulk
from backend.domain.samba.order.model import SambaOrder

KST = timezone(timedelta(hours=9))
_ABC_FAMILY = {"ABCMART", "GRANDSTAGE"}
_ABC_SHIPPING = 2300


def _find_sold_out_option(product_option, options):
    if not product_option or not options:
        return None
    for opt in options:
        if not isinstance(opt, dict):
            continue
        key = (opt.get("name") or opt.get("size") or "").strip()
        if not key or key not in product_option:
            continue
        try:
            stock = int(opt.get("stock") or 0)
        except (TypeError, ValueError):
            stock = 0
        if stock <= 0:
            return key
    return None


async def main() -> None:
    now_kst = datetime.now(KST)
    today_utc = now_kst.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)

    async with get_read_session() as s:
        r = await s.execute(
            select(SambaOrder).where(
                col(SambaOrder.created_at) >= today_utc,
                col(SambaOrder.status) == "pending",
                col(SambaOrder.collected_product_id).is_not(None),
            )
        )
        orders = [
            o for o in r.scalars().all() if not (o.sourcing_order_number or "").strip()
        ]
        print(f"오늘 eligible pending 주문: {len(orders)}건")
        if not orders:
            return

        pids = list({o.collected_product_id for o in orders if o.collected_product_id})
        pr = await s.execute(
            select(SambaCollectedProduct).where(col(SambaCollectedProduct.id).in_(pids))
        )
        products = list(pr.scalars().all())
        product_map = {p.id: p for p in products}

    print(f"상품 {len(products)}개 refresh 중...")
    results, _ = await refresh_products_bulk(products, source="manual")
    rmap = {r.product_id: r for r in results}

    ok = soldout = reverse = hold = 0
    for o in orders:
        r = rmap.get(o.collected_product_id or "")
        prod = product_map.get(o.collected_product_id or "")
        site = (getattr(prod, "source_site", "") or "")
        site_u = site.upper()
        nm = (getattr(prod, "name", "") or "")[:30]
        head = f"[{o.order_number}] {site} qty={o.quantity} rev={o.revenue} | {nm}"
        if r is None:
            print(head, "\n   → 결과없음(보류)")
            hold += 1
            continue
        if r.error or r.needs_extension or r.price_uncertain:
            print(
                head,
                f"\n   → 보류 (error={r.error} needs_ext={r.needs_extension} uncertain={r.price_uncertain})",
            )
            hold += 1
            continue

        is_abc = site_u in _ABC_FAMILY
        benefit = (
            r.new_benefit_cost
            if is_abc
            else r.new_cost
        )
        verdicts = []
        # 재고
        stock_reason = None
        if r.new_sale_status == "sold_out":
            stock_reason = "전체품절"
        else:
            _opt = _find_sold_out_option(o.product_option, r.new_options)
            if _opt:
                stock_reason = f"옵션품절({_opt})"
        # 역마진
        rev_reason = None
        if benefit is not None and benefit > 0 and (o.revenue or 0) > 0:
            qty = int(o.quantity or 1)
            line = float(benefit) * qty
            ship = _ABC_SHIPPING if is_abc else 0
            eff = line + ship
            prof = float(o.revenue) - eff
            if prof < 0:
                rev_reason = f"혜택가{int(benefit):,}x{qty}+{ship}={int(eff):,}>정산{int(o.revenue):,}(손익{int(prof):,})"
        if stock_reason:
            verdicts.append("재고X:" + stock_reason)
            soldout += 1
        if rev_reason:
            verdicts.append("가격X:" + rev_reason)
            reverse += 1
        if not verdicts:
            verdicts.append(
                f"정상(혜택가={benefit} 재고={r.new_sale_status} opt={o.product_option})"
            )
            ok += 1
        print(head, "\n   →", " / ".join(verdicts))

    print(
        f"\n=== 요약: 정상 {ok} / 재고X {soldout} / 가격X {reverse} / 보류 {hold} ==="
    )


asyncio.run(main())
