"""PlayAuto 미등록 주문 → product_name에서 모델번호(style_code) 추출 → CP 매칭.

패턴: 대문자+숫자+하이픈 조합 (예: IB2765-011, DWTP94053, FN5041, 749866)
"""
import asyncio
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text

from backend.db.orm import get_read_session, get_write_session

# 모델번호 패턴: 알파벳 2자 이상 + 숫자 (예: IB2765, FN5041, DWTP94053, DXBK0015N)
MODEL_RE = re.compile(r"\b([A-Z]{2,}[A-Z0-9]{3,}(?:-[A-Z0-9]+)?)\b")
# goods_no 패턴 (기존)
GOODS_NO_RE = re.compile(r"\s+(\d{5,})\s*(?:\([^)]*\))?\s*$")


def extract_model_codes(name: str) -> list[str]:
    """product_name에서 모델번호 후보 추출 (브랜드 약어 제외)."""
    # 너무 짧거나 순수 알파벳만인 것 제외
    codes = []
    for m in MODEL_RE.finditer(name or ""):
        code = m.group(1)
        # 숫자 포함된 것만 (순수 브랜드명 제외)
        if any(c.isdigit() for c in code):
            codes.append(code)
    return codes


async def main() -> None:
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

    print(f"미등록 주문: {len(all_unlinked):,}건")

    # 모델번호 추출
    order_codes: list[tuple[str, list[str]]] = []
    for oid, pn in all_unlinked:
        codes = extract_model_codes(pn or "")
        if codes:
            order_codes.append((str(oid), codes))

    all_codes = {c for _, cs in order_codes for c in cs}
    print(f"모델번호 추출된 주문: {len(order_codes):,}건, unique 코드: {len(all_codes):,}개")

    # CP style_code 인덱스
    async with get_read_session() as s:
        cp_rows = (
            await s.execute(
                text(
                    "SELECT style_code, id FROM samba_collected_product "
                    "WHERE style_code IS NOT NULL AND style_code != '' "
                    "AND style_code = ANY(:codes)"
                ),
                {"codes": list(all_codes)},
            )
        ).fetchall()

    # style_code → cp_id (ambiguous 체크)
    sc_map: dict[str, list[str]] = defaultdict(list)
    for sc, cp_id in cp_rows:
        sc_map[sc].append(str(cp_id))

    unique_sc = {sc: cids[0] for sc, cids in sc_map.items() if len(cids) == 1}
    ambig_sc = {sc for sc, cids in sc_map.items() if len(cids) > 1}
    print(f"매칭된 style_code: {len(sc_map):,}개 (unique={len(unique_sc):,}, ambiguous={len(ambig_sc):,})")

    # 주문 → CP 매칭
    updates: list[tuple[str, str]] = []
    no_code = 0
    ambig = 0
    no_cp = 0
    multi_match = 0

    for oid, codes in order_codes:
        matched_cps = set()
        for code in codes:
            if code in unique_sc:
                matched_cps.add(unique_sc[code])
            elif code in ambig_sc:
                ambig += 1
        if len(matched_cps) == 1:
            updates.append((oid, matched_cps.pop()))
        elif len(matched_cps) > 1:
            multi_match += 1

    # 모델번호 없는 주문
    no_code = len(all_unlinked) - len(order_codes)

    print(f"\n매칭 결과:")
    print(f"  업데이트 가능: {len(updates):,}건")
    print(f"  모델번호 없음: {no_code:,}건")
    print(f"  ambiguous style_code: {ambig:,}건")
    print(f"  CP 여러 개 (multi): {multi_match:,}건")

    if not updates:
        print("\n업데이트 없음")
        return

    print(f"\n샘플:")
    for oid, cp_id in updates[:5]:
        pn = next(pn for r_oid, pn in all_unlinked if str(r_oid) == oid)
        print(f"  {str(pn)[:80]!r} → {cp_id[:25]}")

    # 업데이트 실행
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

    async with get_read_session() as s:
        remaining = (
            await s.execute(
                text("SELECT COUNT(*) FROM samba_order WHERE source='playauto' AND collected_product_id IS NULL")
            )
        ).scalar()
    print(f"잔여 미등록 PlayAuto 주문: {remaining:,}건")


asyncio.run(main())
