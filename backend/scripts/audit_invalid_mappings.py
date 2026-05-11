"""samba_category_mapping 전수조사 — 트리에 없는 경로 추출."""

import asyncio
import asyncpg
import json
from collections import defaultdict
from typing import Any
from backend.core.config import settings


async def main() -> None:
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        # 1) 전체 트리 로드 → 마켓별 valid_paths 세트
        tree_rows = await conn.fetch(
            "SELECT site_name, cat1, cat2 FROM samba_category_tree"
        )
        market_valid: dict[str, set[str]] = {}
        for r in tree_rows:
            site = r["site_name"]
            cat1 = r["cat1"]
            cat2 = r["cat2"]
            if isinstance(cat1, str):
                try:
                    cat1 = json.loads(cat1)
                except Exception:
                    cat1 = None
            if isinstance(cat2, str):
                try:
                    cat2 = json.loads(cat2)
                except Exception:
                    cat2 = None
            paths: set[str] = set()
            if isinstance(cat1, list):
                paths.update(c for c in cat1 if isinstance(c, str))
            if isinstance(cat2, dict):
                paths.update(k for k in cat2.keys() if isinstance(k, str))
            elif isinstance(cat2, list):
                paths.update(c for c in cat2 if isinstance(c, str))
            market_valid[site] = paths
            print(f"[트리] {site}: valid_paths={len(paths)}")

        # 트리 없는 마켓은 검증 불가 → 보고만
        print()

        # 2) 전체 매핑 로드
        rows = await conn.fetch(
            """
            SELECT id, source_site, source_category, target_mappings
            FROM samba_category_mapping
            ORDER BY source_site, source_category
            """
        )
        print(f"[매핑] 전체 {len(rows)}건 검사 시작\n")

        # market별 집계
        per_market_invalid: dict[str, list[tuple[str, str, str, str]]] = defaultdict(
            list
        )
        per_market_total: dict[str, int] = defaultdict(int)
        per_market_skip_no_tree: dict[str, int] = defaultdict(int)
        per_market_skip_empty_tree: dict[str, int] = defaultdict(int)
        invalid_rows: list[dict[str, Any]] = []

        for r in rows:
            tm = r["target_mappings"]
            if isinstance(tm, str):
                try:
                    tm = json.loads(tm)
                except Exception:
                    tm = None
            if not isinstance(tm, dict):
                continue

            row_invalid: dict[str, str] = {}
            for market, path in tm.items():
                if not isinstance(path, str) or not path.strip():
                    continue
                path = path.strip()
                per_market_total[market] += 1
                valid = market_valid.get(market)
                if valid is None:
                    per_market_skip_no_tree[market] += 1
                    continue
                if not valid:
                    per_market_skip_empty_tree[market] += 1
                    continue
                if path not in valid:
                    per_market_invalid[market].append(
                        (r["id"], r["source_site"], r["source_category"], path)
                    )
                    row_invalid[market] = path

            if row_invalid:
                invalid_rows.append(
                    {
                        "id": r["id"],
                        "source_site": r["source_site"],
                        "source_category": r["source_category"],
                        "invalid": row_invalid,
                    }
                )

        # 3) 마켓별 보고
        print("=== 마켓별 잘못된 매핑 카운트 ===")
        markets = sorted(
            set(per_market_total.keys())
            | set(per_market_invalid.keys())
            | set(per_market_skip_no_tree.keys())
            | set(per_market_skip_empty_tree.keys())
        )
        for m in markets:
            total = per_market_total.get(m, 0)
            inv = len(per_market_invalid.get(m, []))
            no_tree = per_market_skip_no_tree.get(m, 0)
            empty = per_market_skip_empty_tree.get(m, 0)
            print(
                f"  {m}: total={total} invalid={inv} no_tree={no_tree} empty_tree={empty}"
            )

        # 4) 잘못된 행 상세 (상위 50건)
        print(f"\n=== 잘못된 매핑 행 상세 (총 {len(invalid_rows)}건) ===")
        for row in invalid_rows[:80]:
            print(
                f"\n[{row['source_site']}] {row['source_category']}  (id={row['id']})"
            )
            for mk, p in row["invalid"].items():
                print(f"   ✗ {mk}: {p}")

        # 5) JSON 저장 (이후 수정 스크립트가 사용)
        out = {
            "summary": {
                m: {
                    "total": per_market_total.get(m, 0),
                    "invalid": len(per_market_invalid.get(m, [])),
                    "no_tree": per_market_skip_no_tree.get(m, 0),
                    "empty_tree": per_market_skip_empty_tree.get(m, 0),
                }
                for m in markets
            },
            "rows": invalid_rows,
        }
        with open("/tmp/invalid_mappings.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("\n[저장] /tmp/invalid_mappings.json")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
