"""잔여 미등록 8,839건 패턴 분석."""
import asyncio
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text

from backend.db.orm import get_read_session

GOODS_NO_RE = re.compile(r"\s+(\d{5,})\s*(?:\(\d+\))?\s*$")


def extract_goods_no(name: str) -> str:
    m = GOODS_NO_RE.search((name or "").strip())
    return m.group(1) if m else ""


async def main() -> None:
    async with get_read_session() as s:
        # 1) goods_no 없는 product_name 샘플 10개
        no_gn = (
            await s.execute(
                text(
                    "SELECT product_name FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL "
                    "AND product_name IS NOT NULL "
                    "AND NOT product_name ~ '\\s\\d{5,}\\s*$' "
                    "LIMIT 10"
                )
            )
        ).fetchall()
        print("goods_no 없는 product_name 샘플:")
        for r in no_gn:
            print(f"  {str(r[0])[:100]!r}")

        # 2) goods_no 있지만 CP 없는 케이스 (DB에 site_product_id 없음)
        # goods_no 추출 가능한 미등록 주문들의 goods_no를 DB site_product_id 에서 검색
        gn_rows = (
            await s.execute(
                text(
                    "SELECT id, product_name FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL "
                    "AND product_name ~ '\\s\\d{5,}\\s*$' "
                    "LIMIT 500"
                )
            )
        ).fetchall()

    gn_list = []
    for _, pn in gn_rows:
        gn = extract_goods_no(pn or "")
        if gn:
            gn_list.append(gn)

    unique_gns = set(gn_list)
    print(f"\ngoods_no 추출 가능 500건에서 unique goods_no: {len(unique_gns)}개")

    async with get_read_session() as s:
        found = (
            await s.execute(
                text(
                    "SELECT site_product_id FROM samba_collected_product "
                    "WHERE site_product_id = ANY(:gns)"
                ),
                {"gns": list(unique_gns)},
            )
        ).fetchall()
        found_set = {r[0] for r in found}
        not_found = unique_gns - found_set
        print(f"  DB에 있는 goods_no: {len(found_set)}개")
        print(f"  DB에 없는 goods_no: {len(not_found)}개")
        print(f"  없는 goods_no 샘플: {list(not_found)[:10]}")

        # 3) 전체 현황 요약
        remaining = (
            await s.execute(
                text(
                    "SELECT COUNT(*), "
                    "SUM(CASE WHEN product_name IS NULL OR product_name='' THEN 1 ELSE 0 END) AS no_name, "
                    "SUM(CASE WHEN product_name ~ '\\s\\d{5,}\\s*$' THEN 1 ELSE 0 END) AS has_gn, "
                    "SUM(CASE WHEN product_name ~ '\\[사본' THEN 1 ELSE 0 END) AS sst_copy "
                    "FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL"
                )
            )
        ).fetchone()
        print(f"\n잔여 미등록 {remaining[0]:,}건 요약:")
        print(f"  product_name 없음: {remaining[1]:,}건")
        print(f"  goods_no 추출 가능: {remaining[2]:,}건")
        print(f"  [사본- 접두어]: {remaining[3]:,}건")

        # 4) [사본- 접두어 제거 후 goods_no 추출 시도
        sst_copy_rows = (
            await s.execute(
                text(
                    "SELECT product_name FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL "
                    "AND product_name ~ '\\[사본' "
                    "LIMIT 5"
                )
            )
        ).fetchall()
        print(f"\n[사본- 샘플:")
        for r in sst_copy_rows:
            pn = str(r[0] or "")
            clean = re.sub(r"^\[사본[^\]]*\]\s*", "", pn)
            gn = extract_goods_no(clean)
            print(f"  원본: {pn[:80]!r}")
            print(f"  정제: {clean[:80]!r} → goods_no={gn!r}")


asyncio.run(main())
