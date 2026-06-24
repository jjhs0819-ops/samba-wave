"""PlayAuto 미등록 주문 → ProdCode 기반 CP 백필.

전략:
  1. 미등록 주문 product_id(마켓 상품번호) 목록 수집
  2. PlayAuto get_orders 폴링 → ProdCode(마켓상품번호) × MasterCode(AM코드) 매핑 생성
  3. product_id → MasterCode → CP ID → collected_product_id UPDATE

order_number(OrderCode) 기반보다 안정적:
  - 같은 product_id 주문이 여러 건 있어도 1회 매핑으로 전체 커버
  - OrderCode 형식 변경에 영향 없음
"""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

os.environ.setdefault(
    "PLAYAUTO_PROXY_URL",
    "http://smart-zhej55fgrt0k:keGU2DZxflfM3QJj@119.206.200.126:6014",
)

from sqlalchemy import text  # noqa: E402

from backend.db.orm import get_read_session, get_write_session  # noqa: E402
from backend.domain.samba.proxy.playauto import PlayAutoApiError, PlayAutoClient  # noqa: E402

PA_ACCOUNT_ID = "ma_01KP0919YA061YX5PHH25KWJAK"
DAYS_BACK = 365  # 1년치 폴링 (미등록 주문이 오래된 것 포함)


async def main() -> None:
    # --- 1) PlayAuto api_key 로드 ---
    async with get_read_session() as s:
        row = (
            await s.execute(
                text("SELECT additional_fields FROM samba_market_account WHERE id = :aid"),
                {"aid": PA_ACCOUNT_ID},
            )
        ).fetchone()
        extras = row[0] or {}
        if isinstance(extras, str):
            extras = json.loads(extras)
        api_key = extras.get("apiKey", "")

    if not api_key:
        print("api_key 없음")
        return

    # --- 2) 미등록 주문 product_id 목록 수집 ---
    async with get_read_session() as s:
        unlinked_rows = (
            await s.execute(
                text(
                    "SELECT DISTINCT product_id FROM samba_order "
                    "WHERE source = 'playauto' AND collected_product_id IS NULL "
                    "AND product_id IS NOT NULL AND product_id != ''"
                )
            )
        ).fetchall()
    target_product_ids = {r[0] for r in unlinked_rows}
    print(f"미등록 주문 product_id 종류: {len(target_product_ids):,}개")
    sample_pids = list(target_product_ids)[:5]
    print(f"  샘플: {sample_pids}")

    # --- 3) AM코드 인덱스 (AM코드 → CP ID) ---
    async with get_read_session() as s:
        am_rows = (
            await s.execute(
                text(
                    "SELECT (cp.market_product_nos->>:kid) AS am_code, cp.id "
                    "FROM samba_collected_product cp "
                    "WHERE cp.market_product_nos ? :kid "
                    "AND (cp.market_product_nos->>:kid) LIKE 'AM%'"
                ),
                {"kid": PA_ACCOUNT_ID},
            )
        ).fetchall()
    am_index = {r[0]: r[1] for r in am_rows if r[0]}
    print(f"AM코드 인덱스: {len(am_index):,}개")

    # --- 4) PlayAuto API 폴링 → ProdCode × MasterCode 매핑 ---
    print(f"\nPlayAuto API 폴링 ({DAYS_BACK}일)...")
    client = PlayAutoClient(api_key=api_key)
    prodcode_to_master: dict[str, str] = {}
    page = 1
    total = 0
    start_date = (datetime.now(UTC) - timedelta(days=DAYS_BACK)).strftime("%Y%m%d")
    try:
        while True:
            try:
                orders = await client.get_orders(start_date=start_date, count=500, page=page)
            except PlayAutoApiError:
                print(f"  page {page}: 주문 없음 (마지막 페이지)")
                break
            if not orders:
                break
            for ro in orders:
                prod_code = str(ro.get("ProdCode", "") or "").strip()
                master_code = str(ro.get("MasterCode", "") or ro.get("SellerCode", "") or "").strip()
                if prod_code and master_code.startswith("AM"):
                    # 같은 ProdCode에 여러 MasterCode가 있으면 처음 것 우선
                    if prod_code not in prodcode_to_master:
                        prodcode_to_master[prod_code] = master_code
            total += len(orders)
            print(f"  page {page}: {len(orders)}건 (누적 {total:,}, 매핑 {len(prodcode_to_master):,})")
            if len(orders) < 500:
                break
            page += 1
    finally:
        await client.close()

    print(f"\nProdCode→MasterCode 매핑: {len(prodcode_to_master):,}개")

    # target_product_ids와 교집합
    hit_pids = target_product_ids & set(prodcode_to_master.keys())
    print(f"미등록 주문 product_id 중 매핑 가능: {len(hit_pids):,}개 / {len(target_product_ids):,}개")

    if not hit_pids:
        print("매핑 가능한 product_id 없음. 종료.")
        return

    # --- 5) 미등록 주문 조회 ---
    async with get_read_session() as s:
        unlinked_all = (
            await s.execute(
                text(
                    "SELECT id, product_id FROM samba_order "
                    "WHERE source = 'playauto' AND collected_product_id IS NULL "
                    "AND product_id = ANY(:pids)"
                ),
                {"pids": list(hit_pids)},
            )
        ).fetchall()
    print(f"업데이트 대상 주문: {len(unlinked_all):,}건")

    # --- 6) 매칭 + DB 업데이트 ---
    updates: list[tuple[str, str]] = []
    no_am_cp = 0

    for row in unlinked_all:
        order_id, product_id = row[0], row[1]
        master_code = prodcode_to_master.get(product_id or "", "")
        if not master_code:
            continue
        cp_id = am_index.get(master_code)
        if not cp_id:
            no_am_cp += 1
            continue
        updates.append((order_id, cp_id))

    print(f"\n최종 업데이트 {len(updates):,}건 (AM→CP 없음 {no_am_cp:,}건)")

    if not updates:
        print("업데이트 없음")
        return

    async with get_write_session() as s:
        cnt = 0
        for order_id, cp_id in updates:
            await s.execute(
                text(
                    "UPDATE samba_order "
                    "SET collected_product_id = :cp, updated_at = NOW() "
                    "WHERE id = :oid AND collected_product_id IS NULL"
                ),
                {"cp": cp_id, "oid": order_id},
            )
            cnt += 1
            if cnt % 200 == 0:
                print(f"  {cnt:,}/{len(updates):,}...")
        await s.commit()

    print(f"\n완료: {cnt:,}건 업데이트")

    # --- 7) 잔여 확인 ---
    async with get_read_session() as s:
        remaining = (
            await s.execute(
                text("SELECT COUNT(*) FROM samba_order WHERE source='playauto' AND collected_product_id IS NULL")
            )
        ).scalar()
    print(f"잔여 미등록 PlayAuto 주문: {remaining:,}건")


asyncio.run(main())
