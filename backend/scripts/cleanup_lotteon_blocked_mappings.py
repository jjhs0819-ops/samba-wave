"""롯데ON 거래처 미허용 카테고리 매핑 일괄 치환.

대상: samba_category_mapping.target_mappings.lotteon
- "패션의류 > ..." 시작 → 성별 추정해 스포츠의류 점퍼 또는 매핑된 동의어로 치환
- 마지막 세그먼트에 "다운" 또는 "패딩" 포함 → 점퍼로 치환

사용:
  cd backend && python scripts/cleanup_lotteon_blocked_mappings.py [--dry-run] [--apply]
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from backend.core.config import settings  # noqa: E402
from backend.db.orm import get_write_engine  # noqa: E402


def _get_engine():
    return get_write_engine()


def _replace_lotteon_path(path: str) -> str | None:
    """차단 대상이면 대체 경로 반환, 아니면 None."""
    if not path:
        return None
    p = path.strip()

    # 1. 패션의류 → 스포츠의류 (성별 유추)
    if p.startswith("패션의류"):
        is_female = "여성" in p
        # 의류 종류별 매핑
        last = p.split(">")[-1].strip()
        if any(kw in last for kw in ("점프", "원피스", "오버올")):
            return (
                "스포츠의류/운동화 > 여성스포츠의류 > 원피스"
                if is_female
                else "스포츠의류/운동화 > 남성스포츠의류 > 점퍼"
            )
        if any(kw in last for kw in ("티셔츠", "반팔")):
            return (
                "스포츠의류/운동화 > 여성스포츠의류 > 반팔티셔츠"
                if is_female
                else "스포츠의류/운동화 > 남성스포츠의류 > 반팔티셔츠"
            )
        if "맨투맨" in last:
            return (
                "스포츠의류/운동화 > 여성스포츠의류 > 맨투맨"
                if is_female
                else "스포츠의류/운동화 > 남성스포츠의류 > 맨투맨"
            )
        if "후드" in last:
            return (
                "스포츠의류/운동화 > 여성스포츠의류 > 후드"
                if is_female
                else "스포츠의류/운동화 > 남성스포츠의류 > 후드"
            )
        if "트레이닝" in last:
            return (
                "스포츠의류/운동화 > 여성스포츠의류 > 트레이닝복"
                if is_female
                else "스포츠의류/운동화 > 남성스포츠의류 > 트레이닝복"
            )
        if "니트" in last or "스웨터" in last:
            return (
                "스포츠의류/운동화 > 여성스포츠의류 > 니트"
                if is_female
                else "스포츠의류/운동화 > 남성스포츠의류 > 니트"
            )
        if "가디건" in last or "카디건" in last:
            return (
                "스포츠의류/운동화 > 여성스포츠의류 > 가디건"
                if is_female
                else "스포츠의류/운동화 > 남성스포츠의류 > 가디건"
            )
        if "셔츠" in last or "블라우스" in last:
            return (
                "스포츠의류/운동화 > 여성스포츠의류 > 긴팔티셔츠"
                if is_female
                else "스포츠의류/운동화 > 남성스포츠의류 > 긴팔티셔츠"
            )
        if "스커트" in last:
            return "스포츠의류/운동화 > 여성스포츠의류 > 스커트"
        if any(kw in last for kw in ("바지", "팬츠", "청바지", "슬랙스", "레깅스")):
            return (
                "스포츠의류/운동화 > 여성스포츠의류 > 긴바지"
                if is_female
                else "스포츠의류/운동화 > 남성스포츠의류 > 긴바지"
            )
        if any(
            kw in last
            for kw in ("패딩", "다운", "점퍼", "자켓", "재킷", "코트", "아우터")
        ):
            return (
                "스포츠의류/운동화 > 여성스포츠의류 > 점퍼"
                if is_female
                else "스포츠의류/운동화 > 남성스포츠의류 > 점퍼"
            )
        # 기본: 점퍼
        return (
            "스포츠의류/운동화 > 여성스포츠의류 > 점퍼"
            if is_female
            else "스포츠의류/운동화 > 남성스포츠의류 > 점퍼"
        )

    # 2. 스포츠의류 + 다운/패딩 → 점퍼
    if "스포츠의류" in p:
        last = p.split(">")[-1].strip()
        if any(kw in last for kw in ("다운", "패딩")):
            is_female = "여성스포츠의류" in p
            return (
                "스포츠의류/운동화 > 여성스포츠의류 > 점퍼"
                if is_female
                else "스포츠의류/운동화 > 남성스포츠의류 > 점퍼"
            )

    return None


async def main() -> None:
    apply = "--apply" in sys.argv
    dry_run = not apply

    engine = _get_engine()
    print(
        f"DB: {settings.write_db_host}:{settings.write_db_port}/{settings.write_db_name}"
    )
    print(f"모드: {'APPLY' if apply else 'DRY-RUN'}")

    async with engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, source_site, source_category, target_mappings "
                "FROM samba_category_mapping "
                "WHERE target_mappings::text LIKE '%lotteon%'"
            )
        )
        rows = rows.fetchall()
        print(f"롯데ON 매핑 보유 row: {len(rows)}건")

        changed = []
        for r in rows:
            tm = dict(r.target_mappings or {})
            cur = tm.get("lotteon", "")
            new = _replace_lotteon_path(cur)
            if new and new != cur:
                tm["lotteon"] = new
                changed.append((r.id, r.source_site, r.source_category, cur, new, tm))

        print(f"치환 대상: {len(changed)}건")
        for cid, ss, sc, cur, new, _ in changed[:20]:
            print(f"  [{cid}] {ss}/{sc}: '{cur}' → '{new}'")
        if len(changed) > 20:
            print(f"  ... +{len(changed) - 20}건")

        if apply and changed:
            for cid, _, _, _, _, tm in changed:
                await conn.execute(
                    text(
                        "UPDATE samba_category_mapping SET target_mappings = :tm "
                        "WHERE id = :id"
                    ),
                    {"tm": __import__("json").dumps(tm, ensure_ascii=False), "id": cid},
                )
            print(f"✅ {len(changed)}건 UPDATE 완료")
        elif dry_run:
            print("(--apply 옵션 없이 dry-run 모드. 실제 변경 안 함)")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
