"""오늘 주문건 자동판정 동작 점검 (읽기전용).

- 오늘(KST) 주문 집계 + 자동판정 대상(eligible) 필터링 현황
- 자동태그(no_price/no_stock) 또는 자동 메모 붙은 건 나열 + 새 가드로 재검증
- 발주완료/비기본상태가 제대로 제외되는지 확인
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlmodel import col, or_, select

from backend.db.orm import get_read_session
from backend.domain.samba.order.model import SambaOrder

KST = timezone(timedelta(hours=9))
_ACTIVE = ("pending",)


async def main() -> None:
    now_kst = datetime.now(KST)
    today_start_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_kst.astimezone(timezone.utc)

    async with get_read_session() as s:
        # 오늘 생성된 주문 전체
        r = await s.execute(
            select(SambaOrder).where(col(SambaOrder.created_at) >= today_start_utc)
        )
        orders = list(r.scalars().all())
        print(f"오늘({today_start_kst:%Y-%m-%d} KST~) 주문 총 {len(orders)}건")

        # 상태 분포
        by_status: dict[str, int] = {}
        for o in orders:
            by_status[o.status] = by_status.get(o.status, 0) + 1
        print("상태분포:", by_status)

        # eligible (자동판정 대상): pending + 미발주 + cp연결
        eligible = [
            o
            for o in orders
            if o.status in _ACTIVE
            and not (o.sourcing_order_number or "").strip()
            and o.collected_product_id
        ]
        print(f"자동판정 대상(eligible): {len(eligible)}건")
        print(
            "  제외사유 — 비pending:",
            sum(1 for o in orders if o.status not in _ACTIVE),
            "/ 발주완료:",
            sum(1 for o in orders if (o.sourcing_order_number or '').strip()),
            "/ cp미연결:",
            sum(1 for o in orders if not o.collected_product_id),
        )

        # 자동태그/자동메모 붙은 건 점검
        print("\n=== 자동판정 흔적 있는 주문 ===")
        hit = 0
        for o in orders:
            tags = [t for t in (o.action_tag or "").split(",") if t.strip()]
            has_auto_tag = ("no_price" in tags) or ("no_stock" in tags)
            has_auto_note = "자동:" in (o.notes or "")
            if not (has_auto_tag or has_auto_note):
                continue
            hit += 1
            # 새 가드 기준 여전히 대상인가?
            still_eligible = (
                o.status in _ACTIVE
                and not (o.sourcing_order_number or "").strip()
                and o.collected_product_id
            )
            flag = "" if still_eligible else "  ← 새 가드면 제외대상(과거 오판 가능)"
            print(f"[{o.order_number}] {o.source_site} status={o.status}")
            print(
                f"   tags={tags} 발주={o.sourcing_order_number or '-'} "
                f"cost={o.cost} revenue={o.revenue} ship={o.shipping_fee} profit={o.profit}{flag}"
            )
            _auto_lines = [
                ln for ln in (o.notes or "").splitlines() if "자동:" in ln
            ]
            for ln in _auto_lines[-2:]:
                print("   note:", ln.strip())
        if not hit:
            print("(없음)")


asyncio.run(main())
