"""PlayAuto 미등록 주문 → MasterCode 기반 CP 백필.

PlayAuto API에서 과거 주문 재폴링 → MasterCode → mpnos 매칭 → collected_product_id UPDATE.
실행: docker exec samba-samba-api-1 /app/backend/.venv/bin/python3 /tmp/backfill_playauto_cp_link.py
"""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

# 인증 포함 프록시
os.environ.setdefault(
    "PLAYAUTO_PROXY_URL",
    "http://smart-zhej55fgrt0k:keGU2DZxflfM3QJj@119.206.200.126:6014",
)

from sqlalchemy import text  # noqa: E402

from backend.db.orm import get_read_session, get_write_session  # noqa: E402
from backend.domain.samba.proxy.playauto import PlayAutoClient  # noqa: E402

PA_ACCOUNT_ID = "ma_01KP0919YA061YX5PHH25KWJAK"
DAYS_BACK = 180  # 6개월 과거까지 폴링


async def load_mpn_am_index() -> dict[str, str]:
    """DB에서 AM코드 → collected_product_id 인덱스 생성."""
    async with get_read_session() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT (cp.market_product_nos->>:kid) AS am_code, cp.id "
                    "FROM samba_collected_product cp "
                    "WHERE jsonb_typeof(cp.market_product_nos) = 'object' "
                    "AND cp.market_product_nos ? :kid "
                    "AND (cp.market_product_nos->>:kid) LIKE 'AM%'"
                ),
                {"kid": PA_ACCOUNT_ID},
            )
        ).fetchall()
    result = {r[0]: r[1] for r in rows if r[0]}
    print(f"AM코드 인덱스: {len(result):,}개")
    return result


async def load_unlinked_orders() -> dict[str, str]:
    """미등록 PlayAuto 주문 order_number → id 매핑."""
    async with get_read_session() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT order_number, id FROM samba_order "
                    "WHERE source = 'playauto' "
                    "AND collected_product_id IS NULL "
                    "AND order_number IS NOT NULL AND order_number != ''"
                )
            )
        ).fetchall()
    result = {r[0]: r[1] for r in rows}
    print(f"미등록 PlayAuto 주문: {len(result):,}건")
    return result


async def fetch_playauto_orders(api_key: str, days: int) -> list[dict]:
    """PlayAuto API에서 과거 N일 주문 전체 폴링 (페이징)."""
    client = PlayAutoClient(api_key=api_key)
    all_orders = []
    page = 1
    count = 500
    start_date = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y%m%d")
    try:
        while True:
            orders = await client.get_orders(
                start_date=start_date,
                count=count,
                page=page,
            )
            if not orders:
                break
            all_orders.extend(orders)
            print(f"  page {page}: {len(orders)}건 (누적 {len(all_orders):,}건)")
            if len(orders) < count:
                break
            page += 1
    finally:
        await client.close()
    return all_orders


async def main() -> None:
    # 1) PlayAuto 계정 api_key 로드
    async with get_read_session() as s:
        row = (
            await s.execute(
                text(
                    "SELECT additional_fields FROM samba_market_account "
                    "WHERE id = :aid"
                ),
                {"aid": PA_ACCOUNT_ID},
            )
        ).fetchone()
        if not row:
            print("PlayAuto 계정 없음")
            return
        extras = row[0] or {}
        if isinstance(extras, str):
            extras = json.loads(extras)
        api_key = extras.get("apiKey", "")

    if not api_key:
        print("api_key 없음")
        return

    # 2) DB 인덱스 로드
    am_index = await load_mpn_am_index()
    unlinked = await load_unlinked_orders()

    if not unlinked:
        print("미등록 주문 없음")
        return

    # 3) PlayAuto API 폴링
    print(f"\nPlayAuto API 폴링 (최근 {DAYS_BACK}일)...")
    raw_orders = await fetch_playauto_orders(api_key, DAYS_BACK)
    print(f"PlayAuto 주문 총 {len(raw_orders):,}건 수신")

    # 4) MasterCode 추출 + 매칭
    matches: list[tuple[str, str, str]] = []  # (order_id, cp_id, master_code)
    no_mastercode = 0
    no_match = 0

    for ro in raw_orders:
        # order_number = OrderCode (order.py:10102 확인)
        order_no = str(ro.get("OrderCode", "") or "")
        if not order_no:
            continue

        # 미등록 주문인지 확인
        order_id = unlinked.get(order_no)
        if not order_id:
            continue  # 이미 linked이거나 PlayAuto 주문 아님

        # MasterCode 추출
        master_code = (
            ro.get("MasterCode")
            or ro.get("SellerCode")
            or ""
        )
        if not master_code or not master_code.startswith("AM"):
            no_mastercode += 1
            continue

        # AM코드 → CP 매칭
        cp_id = am_index.get(master_code)
        if not cp_id:
            no_match += 1
            continue

        matches.append((order_id, cp_id, master_code))

    print(f"\n매칭 결과:")
    print(f"  매칭 성공: {len(matches):,}건")
    print(f"  MasterCode 없음: {no_mastercode:,}건")
    print(f"  AM코드 → CP 없음 (미등록 상품): {no_match:,}건")

    if not matches:
        print("\n업데이트할 건 없음")
        return

    # 5) DB 업데이트
    print(f"\n{len(matches):,}건 collected_product_id 업데이트 중...")
    updated = 0
    async with get_write_session() as s:
        for order_id, cp_id, master_code in matches:
            await s.execute(
                text(
                    "UPDATE samba_order "
                    "SET collected_product_id = :cp_id, "
                    "    updated_at = NOW() "
                    "WHERE id = :oid "
                    "AND collected_product_id IS NULL"
                ),
                {"cp_id": cp_id, "oid": order_id},
            )
            updated += 1
            if updated % 100 == 0:
                print(f"  {updated:,}/{len(matches):,} 완료...")
        await s.commit()

    print(f"\n완료: {updated:,}건 업데이트")

    # 6) 잔여 미등록 확인
    async with get_read_session() as s:
        remaining = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM samba_order "
                    "WHERE source = 'playauto' AND collected_product_id IS NULL"
                )
            )
        ).scalar()
    print(f"잔여 미등록 PlayAuto 주문: {remaining:,}건")


asyncio.run(main())
