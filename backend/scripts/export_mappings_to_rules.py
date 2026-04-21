"""프로덕션 카테고리 매핑 데이터를 rules_exported.py로 내보내기.

DB의 samba_category_mapping 테이블에서 매핑 데이터를 읽어
backend/domain/samba/category/rules_exported.py 파일을 갱신한다.
이 파일은 AI few-shot 학습 예시와 룰 기반 1단계 매핑에 사용된다.

사용법:
  cd backend
  python scripts/export_mappings_to_rules.py
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))


async def main() -> None:
    from sqlmodel import select
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

    from backend.core.config import settings
    from backend.domain.samba.category.model import SambaCategoryMapping

    engine = create_async_engine(settings.database_url_write, echo=False)

    async with AsyncSession(engine) as session:
        stmt = select(SambaCategoryMapping)
        result = await session.execute(stmt)
        rows = result.scalars().all()

    await engine.dispose()

    # { (source_site, market): { source_category: target_category } }
    exported: dict[tuple[str, str], dict[str, str]] = {}
    skipped = 0

    for row in rows:
        if not row.target_mappings or not isinstance(row.target_mappings, dict):
            continue
        site = (row.source_site or "").strip()
        src_cat = (row.source_category or "").strip()
        if not site or not src_cat:
            continue

        for market, tgt_cat in row.target_mappings.items():
            if not tgt_cat or not isinstance(tgt_cat, str):
                continue
            tgt_cat = tgt_cat.strip()
            # 대분류 단독값은 학습 데이터에서도 제외
            if " > " not in tgt_cat:
                skipped += 1
                continue
            key = (site, market)
            if key not in exported:
                exported[key] = {}
            exported[key][src_cat] = tgt_cat

    total = sum(len(v) for v in exported.values())
    print(f"매핑 행: {len(rows)}개 → 학습 데이터: {total}건 (대분류 제외: {skipped}건)")

    # rules_exported.py 생성
    out_path = (
        Path(__file__).parent.parent
        / "backend"
        / "domain"
        / "samba"
        / "category"
        / "rules_exported.py"
    )

    lines = [
        '"""프로덕션 카테고리 매핑 학습 데이터.',
        "",
        "export_mappings_to_rules.py 스크립트로 자동 생성됨. 직접 편집 금지.",
        "소스코드를 공유받은 모든 테넌트가 이 룰을 즉시 활용 가능.",
        "",
        f"생성 일시: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"총 건수: {total}",
        '"""',
        "",
        "# (source_site, target_market) → {source_category: target_category}",
        "EXPORTED_RULES: dict[tuple[str, str], dict[str, str]] = {",
    ]

    for (site, market), mapping in sorted(exported.items()):
        lines.append(f"    # {site} → {market} ({len(mapping)}건)")
        lines.append(f"    ({site!r}, {market!r}): {{")
        for src, tgt in sorted(mapping.items()):
            lines.append(f"        {src!r}: {tgt!r},")
        lines.append("    },")

    lines.append("}")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"저장 완료: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
