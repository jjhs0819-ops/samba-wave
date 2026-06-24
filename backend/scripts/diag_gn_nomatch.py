"""goods_no 있지만 CP 없는 케이스 상세 분석."""
import asyncio
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text

from backend.db.orm import get_read_session

# 개선된 패턴: 끝 괄호(나이키) 허용
GOODS_NO_RE = re.compile(r"\s+(\d{5,})\s*(?:\([^)]*\))?\s*$")


def extract_goods_no(name: str) -> str:
    m = GOODS_NO_RE.search((name or "").strip())
    return m.group(1) if m else ""


async def main() -> None:
    async with get_read_session() as s:
        # 개선 패턴으로 추출 가능 건수 확인
        # Python 레벨에서 확인
        all_unlinked = (
            await s.execute(
                text(
                    "SELECT id, product_name FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL "
                    "AND product_name IS NOT NULL"
                )
            )
        ).fetchall()

    all_gns = [(str(r[0]), extract_goods_no(r[1] or "")) for r in all_unlinked]
    with_gn = [(oid, gn) for oid, gn in all_gns if gn]
    unique_gns = {gn for _, gn in with_gn}
    print(f"개선 패턴으로 goods_no 추출: {len(with_gn):,}건, unique: {len(unique_gns):,}개")

    # site_product_id 검색
    async with get_read_session() as s:
        found = (
            await s.execute(
                text(
                    "SELECT site_product_id, id, source_site FROM samba_collected_product "
                    "WHERE site_product_id = ANY(:gns)"
                ),
                {"gns": list(unique_gns)},
            )
        ).fetchall()
    found_map = {r[0]: (r[1], r[2]) for r in found}
    print(f"DB에서 찾은 goods_no: {len(found_map):,}개")
    print(f"DB에 없는 goods_no: {len(unique_gns) - len(found_map):,}개")

    # 없는 goods_no 샘플
    not_found = [gn for gn in sorted(unique_gns) if gn not in found_map]
    print(f"\nDB에 없는 goods_no 샘플 (길이별):")
    by_len: dict[int, list[str]] = {}
    for gn in not_found:
        by_len.setdefault(len(gn), []).append(gn)
    for L in sorted(by_len):
        print(f"  {L}자리: {by_len[L][:5]} ({len(by_len[L])}개)")

    # 없는 goods_no 중 샘플 product_name 확인
    sample_not_found = set(not_found[:5])
    sample_pnames = [(oid, gn) for oid, gn in with_gn if gn in sample_not_found][:5]
    async with get_read_session() as s:
        for oid, gn in sample_pnames:
            row = (
                await s.execute(
                    text("SELECT product_name FROM samba_order WHERE id = :oid"),
                    {"oid": oid},
                )
            ).fetchone()
            print(f"\n  goods_no={gn!r}: {str(row[0])[:100]!r}")
            # style_code로도 검색
            style_rows = (
                await s.execute(
                    text(
                        "SELECT id, site_product_id, source_site, style_code FROM samba_collected_product "
                        "WHERE style_code = :gn LIMIT 3"
                    ),
                    {"gn": gn},
                )
            ).fetchall()
            if style_rows:
                print(f"    style_code 매칭: {[(r[1], r[2], r[3]) for r in style_rows]}")


asyncio.run(main())
