"""PlayAuto 미등록 주문 → product_name 끝 숫자(소싱처 상품번호)로 CP 백필.

PlayAuto ProdName 끝 숫자 = CP site_product_id (검증 완료: 4/4 일치).
PlayAuto API 재폴링 없이 DB order.product_name에서 직접 추출 가능.

보수적 매칭:
  - product_name 끝 숫자 5자리 이상
  - site_product_id 정확 일치 (LIKE 불사용)
  - 동일 site_product_id에 CP 1개만 있을 때만 적용 (ambiguous 방지)
"""
import asyncio
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text

from backend.db.orm import get_read_session, get_write_session

GOODS_NO_RE = re.compile(r"\s+(\d{5,})\s*(?:\(\d+\))?\s*$")


def extract_goods_no(name: str) -> str:
    """product_name 끝에서 소싱처 goods_no 추출."""
    m = GOODS_NO_RE.search((name or "").strip())
    return m.group(1) if m else ""


async def main() -> None:
    async with get_read_session() as s:
        # 미등록 주문의 product_name 샘플 확인
        samples = (
            await s.execute(
                text(
                    "SELECT order_number, product_name, product_id "
                    "FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL "
                    "AND product_name IS NOT NULL "
                    "LIMIT 10"
                )
            )
        ).fetchall()
        print("미등록 주문 product_name 샘플:")
        for r in samples:
            gn = extract_goods_no(r[1] or "")
            print(f"  order_no={r[0]!r}")
            print(f"  product_name={str(r[1])[:80]!r}")
            print(f"  → goods_no={gn!r}")
            print()

        # goods_no 추출 가능한 미등록 주문 수 확인
        # PostgreSQL regex 활용
        cnt_with_gn = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL "
                    "AND product_name IS NOT NULL "
                    "AND product_name ~ '\\s\\d{5,}\\s*$'"
                )
            )
        ).scalar()
        cnt_total = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL"
                )
            )
        ).scalar()
        print(f"goods_no 추출 가능 미등록 주문: {cnt_with_gn:,}/{cnt_total:,}건")

        # site_product_id 인덱스 빌드 (CP ID당 하나만)
        spid_rows = (
            await s.execute(
                text(
                    "SELECT site_product_id, id FROM samba_collected_product "
                    "WHERE site_product_id IS NOT NULL AND site_product_id != ''"
                )
            )
        ).fetchall()

    # site_product_id → cp_id 매핑 (ambiguous 제거)
    spid_map: dict[str, str | None] = {}
    for spid, cp_id in spid_rows:
        key = str(spid)
        if key in spid_map:
            spid_map[key] = None  # ambiguous
        else:
            spid_map[key] = str(cp_id)
    unique_spids = sum(1 for v in spid_map.values() if v is not None)
    print(f"\nsite_product_id 인덱스: {len(spid_map):,}개 (unique={unique_spids:,}개)")

    # 미등록 주문 전체 로드 + goods_no 추출 + 매칭
    async with get_read_session() as s:
        all_unlinked = (
            await s.execute(
                text(
                    "SELECT id, product_name FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL "
                    "AND product_name IS NOT NULL"
                )
            )
        ).fetchall()

    print(f"\n미등록 주문 처리 중: {len(all_unlinked):,}건")

    updates: list[tuple[str, str]] = []
    no_goods_no = 0
    ambiguous = 0
    no_cp = 0

    for order_id, prod_name in all_unlinked:
        gn = extract_goods_no(prod_name or "")
        if not gn:
            no_goods_no += 1
            continue
        cp_id = spid_map.get(gn)
        if cp_id is None:
            if gn in spid_map:
                ambiguous += 1
            else:
                no_cp += 1
            continue
        updates.append((str(order_id), cp_id))

    print(f"매칭 결과:")
    print(f"  업데이트 가능: {len(updates):,}건")
    print(f"  goods_no 없음: {no_goods_no:,}건")
    print(f"  ambiguous (CP 2개+): {ambiguous:,}건")
    print(f"  CP 없음: {no_cp:,}건")

    if not updates:
        print("\n업데이트 없음")
        return

    print(f"\n샘플 업데이트 대상:")
    for oid, cp_id in updates[:5]:
        print(f"  order_id={oid[:20]} → CP={cp_id[:25]}")

    # DB 업데이트
    async with get_write_session() as s:
        cnt = 0
        for oid, cp_id in updates:
            await s.execute(
                text(
                    "UPDATE samba_order "
                    "SET collected_product_id = :cp, updated_at = NOW() "
                    "WHERE id = :oid AND collected_product_id IS NULL"
                ),
                {"cp": cp_id, "oid": oid},
            )
            cnt += 1
            if cnt % 500 == 0:
                print(f"  {cnt:,}/{len(updates):,}...")
        await s.commit()

    print(f"\n완료: {cnt:,}건 업데이트")

    # 잔여 확인
    async with get_read_session() as s:
        remaining = (
            await s.execute(
                text("SELECT COUNT(*) FROM samba_order WHERE source='playauto' AND collected_product_id IS NULL")
            )
        ).scalar()
    print(f"잔여 미등록 PlayAuto 주문: {remaining:,}건")


asyncio.run(main())
