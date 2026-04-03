"""GS샵 쿠팡 대량 등록 준비 스크립트.

GS샵 수집 상품의 카테고리 자동 매핑 + tenant_id NULL 보정 + 카테고리 매핑 INSERT.

처리 흐름:
  1단계: 현황 진단 (카테고리 비어있는 상품, tenant_id NULL 상품)
  2단계: 상품명 기반 카테고리 매핑 UPDATE
  3단계: tenant_id NULL 보정
  4단계: samba_category_mapping INSERT
  5단계: 결과 리포트

실행:
  cd backend
  source .venv/bin/activate
  python scripts/prepare_gsshop_coupang.py
"""

import json
import sys
from datetime import datetime, timezone

import psycopg2
from ulid import ULID

# 상품명 키워드 → 카테고리 매핑 (우선순위 순서)
KEYWORD_CATEGORY_MAP: list[tuple[str, str, list[str]]] = [
    # (키워드, 카테고리 경로, 제외 키워드)
    ("세트", "패션의류잡화 > 키즈 의류(3~8세) > 남녀공용의류 > 상하복 세트", []),
    ("원피스", "패션의류잡화 > 키즈 의류(3~8세) > 남녀공용의류 > 원피스", ["세트"]),
    ("바지", "패션의류잡화 > 키즈 의류(3~8세) > 남녀공용의류 > 바지", ["세트"]),
    ("티셔츠", "패션의류잡화 > 키즈 의류(3~8세) > 남녀공용의류 > 티셔츠", ["세트"]),
]
DEFAULT_CATEGORY = "기타 재화"


def find_coupang_code(
    source_category: str,
    coupang_cat2: dict[str, str],
) -> str | None:
    """source_category의 마지막 세그먼트를 쿠팡 cat2 경로에서 매칭."""
    if not source_category:
        return None

    segments = [s.strip() for s in source_category.split(">")]
    keyword = segments[-1] if segments else ""
    if not keyword:
        return None

    # 1순위: 최하위 세그먼트 완전일치
    for path, code in coupang_cat2.items():
        path_segments = [s.strip() for s in path.split(">")]
        last_segment = path_segments[-1] if path_segments else ""
        if last_segment == keyword:
            print(f"  [완전일치] '{keyword}' → {path} (코드: {code})")
            return str(code)

    # 2순위: 경로 내 부분일치
    candidates: list[tuple[str, str]] = []
    for path, code in coupang_cat2.items():
        if keyword in path:
            candidates.append((path, str(code)))

    if candidates:
        best = min(candidates, key=lambda x: len(x[0]))
        print(f"  [부분일치] '{keyword}' → {best[0]} (코드: {best[1]})")
        return best[1]

    return None


def main() -> None:
    conn = psycopg2.connect(
        host="localhost",
        port=5433,
        dbname="test_little_boy",
        user="test_user",
        password="test_password",
    )
    cur = conn.cursor()

    try:
        # ============================================================
        # 1단계: 현황 진단
        # ============================================================
        print("=" * 60)
        print("1단계: 현황 진단")
        print("=" * 60)

        cur.execute("""
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site = 'GSShop'
        """)
        total = cur.fetchone()[0]
        print(f"  전체 GS샵 상품: {total}건")

        cur.execute("""
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site = 'GSShop' AND (category IS NULL OR category = '')
        """)
        empty_cat = cur.fetchone()[0]
        print(f"  카테고리 비어있는 상품: {empty_cat}건")

        cur.execute("""
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site = 'GSShop' AND tenant_id IS NULL
        """)
        null_tenant = cur.fetchone()[0]
        print(f"  tenant_id NULL 상품: {null_tenant}건")

        if total == 0:
            print("\nGS샵 수집 상품이 없습니다.")
            sys.exit(0)

        print()

        # ============================================================
        # 2단계: 상품명 기반 카테고리 매핑 UPDATE
        # ============================================================
        print("=" * 60)
        print("2단계: 상품명 기반 카테고리 매핑")
        print("=" * 60)

        total_updated = 0

        for keyword, category_path, excludes in KEYWORD_CATEGORY_MAP:
            # 제외 키워드 조건 생성
            exclude_clause = ""
            params: list[str] = [category_path]
            for ex in excludes:
                exclude_clause += " AND name NOT LIKE %s"
                params.append(f"%{ex}%")

            query = f"""
                UPDATE samba_collected_product
                SET category = %s, updated_at = NOW()
                WHERE source_site = 'GSShop'
                  AND (category IS NULL OR category = '')
                  AND name LIKE %s
                  {exclude_clause}
            """
            params.insert(1, f"%{keyword}%")

            cur.execute(query, params)
            updated = cur.rowcount
            total_updated += updated
            print(f"  '{keyword}' → {category_path}: {updated}건 업데이트")

        # 나머지: 기타 재화
        cur.execute("""
            UPDATE samba_collected_product
            SET category = %s, updated_at = NOW()
            WHERE source_site = 'GSShop'
              AND (category IS NULL OR category = '')
        """, (DEFAULT_CATEGORY,))
        default_updated = cur.rowcount
        total_updated += default_updated
        print(f"  '기타(나머지)' → {DEFAULT_CATEGORY}: {default_updated}건 업데이트")

        print(f"\n  총 카테고리 업데이트: {total_updated}건")
        print()

        # ============================================================
        # 3단계: tenant_id NULL 보정
        # ============================================================
        print("=" * 60)
        print("3단계: tenant_id NULL 보정")
        print("=" * 60)

        if null_tenant > 0:
            # 기존 GS샵 상품 중 tenant_id가 있는 값 조회
            cur.execute("""
                SELECT DISTINCT tenant_id FROM samba_collected_product
                WHERE source_site = 'GSShop' AND tenant_id IS NOT NULL
                LIMIT 1
            """)
            row = cur.fetchone()

            if row and row[0]:
                ref_tenant_id = row[0]
                print(f"  참조 tenant_id: {ref_tenant_id}")

                cur.execute("""
                    UPDATE samba_collected_product
                    SET tenant_id = %s, updated_at = NOW()
                    WHERE source_site = 'GSShop' AND tenant_id IS NULL
                """, (ref_tenant_id,))
                tenant_updated = cur.rowcount
                print(f"  tenant_id 보정: {tenant_updated}건")
            else:
                print("  WARNING: 참조할 tenant_id가 없습니다. 수동 지정 필요.")
        else:
            print("  tenant_id NULL 없음 — 보정 불필요")

        print()

        # ============================================================
        # 4단계: samba_category_mapping INSERT
        # ============================================================
        print("=" * 60)
        print("4단계: samba_category_mapping INSERT")
        print("=" * 60)

        # 기존 GSShop 매핑 삭제 후 재생성
        cur.execute(
            "DELETE FROM samba_category_mapping WHERE source_site = 'GSShop'"
        )
        deleted = cur.rowcount
        print(f"  기존 GSShop 매핑 {deleted}건 삭제")

        # 쿠팡 cat2 트리 로드
        cur.execute(
            "SELECT cat2 FROM samba_category_tree WHERE site_name = 'coupang'"
        )
        tree_row = cur.fetchone()
        if not tree_row or not tree_row[0]:
            print("  WARNING: 쿠팡 카테고리 트리(cat2)가 없습니다. 매핑 INSERT 스킵.")
        else:
            coupang_cat2: dict[str, str] = tree_row[0]
            if isinstance(coupang_cat2, str):
                coupang_cat2 = json.loads(coupang_cat2)
            print(f"  쿠팡 cat2 경로 {len(coupang_cat2)}건 로드")

            # GS샵 상품의 고유 카테고리 조회
            cur.execute("""
                SELECT DISTINCT category
                FROM samba_collected_product
                WHERE source_site = 'GSShop' AND category IS NOT NULL AND category != ''
            """)
            categories = [row[0] for row in cur.fetchall()]
            print(f"  GS샵 고유 카테고리 {len(categories)}건")

            inserted = 0
            skipped_nomatch = 0

            for source_category in categories:
                print(f"\n  [{source_category}]")

                matched_code = find_coupang_code(source_category, coupang_cat2)
                if not matched_code:
                    print(f"    SKIP: 매칭 실패 — 수동 매핑 필요")
                    skipped_nomatch += 1
                    continue

                now = datetime.now(tz=timezone.utc)
                mapping_id = f"cm_{ULID()}"
                target_mappings = json.dumps({"coupang": matched_code})

                cur.execute("""
                    INSERT INTO samba_category_mapping
                    (id, source_site, source_category, target_mappings, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (mapping_id, "GSShop", source_category, target_mappings, now, now))
                print(f"    INSERT: id={mapping_id}, coupang={matched_code}")
                inserted += 1

            print(f"\n  매핑 INSERT: {inserted}건, 매칭실패: {skipped_nomatch}건")

        # 커밋
        conn.commit()
        print("\n  DB 커밋 완료")
        print()

        # ============================================================
        # 5단계: 결과 리포트
        # ============================================================
        print("=" * 60)
        print("5단계: 결과 리포트")
        print("=" * 60)

        # 카테고리별 상품 수
        print("\n  [카테고리별 상품 수]")
        cur.execute("""
            SELECT category, COUNT(*) as cnt
            FROM samba_collected_product
            WHERE source_site = 'GSShop'
            GROUP BY category
            ORDER BY cnt DESC
        """)
        for cat, cnt in cur.fetchall():
            print(f"    {cat or '(빈값)'}: {cnt}건")

        # tenant_id 확인
        print("\n  [tenant_id NULL 잔존 확인]")
        cur.execute("""
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site = 'GSShop' AND tenant_id IS NULL
        """)
        remaining_null = cur.fetchone()[0]
        print(f"    tenant_id NULL: {remaining_null}건")

        # 카테고리 매핑 확인
        print("\n  [GSShop 카테고리 매핑]")
        cur.execute("""
            SELECT source_category, target_mappings
            FROM samba_category_mapping
            WHERE source_site = 'GSShop'
            ORDER BY created_at
        """)
        for row in cur.fetchall():
            mappings = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            print(f"    {row[0]} → coupang:{mappings.get('coupang', 'N/A')}")

        print("\n완료!")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
