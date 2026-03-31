"""GSShop → 쿠팡 카테고리 매핑 INSERT 스크립트.

GSShop 수집 상품의 카테고리를 쿠팡 cat2 트리에서 키워드 매칭하여
samba_category_mapping 테이블에 INSERT한다.

source_category는 shipment service와 동일하게 category1~4 join으로 구성한다.

실행:
  cd backend
  source .venv/bin/activate
  python scripts/insert_gsshop_coupang_mapping.py
"""

import json
import sys
from datetime import datetime, timezone

import psycopg2
from ulid import ULID


def find_best_match(
    source_category: str,
    coupang_cat2: dict[str, str],
) -> str | None:
    """source_category의 마지막 세그먼트를 쿠팡 cat2 경로에서 매칭.

    1순위: 경로 최하위 세그먼트 완전일치
    2순위: 경로 내 부분일치 (contains)
    """
    if not source_category:
        return None

    # join된 경로의 마지막 세그먼트를 키워드로 사용
    segments = [s.strip() for s in source_category.split(">")]
    keyword = segments[-1] if segments else ""
    if not keyword:
        return None

    # 1순위: 최하위 세그먼트 완전일치
    for path, code in coupang_cat2.items():
        # 경로 형식: "대분류 > 중분류 > 소분류"
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
        # 경로가 가장 짧은(더 구체적인) 후보 선택
        best = min(candidates, key=lambda x: len(x[0]))
        print(f"  [부분일치] '{keyword}' → {best[0]} (코드: {best[1]})")
        return best[1]

    return None


def main() -> None:
    # DB 연결
    conn = psycopg2.connect(
        host="localhost",
        port=5433,
        dbname="test_little_boy",
        user="test_user",
        password="test_password",
    )
    cur = conn.cursor()

    try:
        # 0단계: 기존 잘못된 GSShop 매핑 삭제
        print("=== 0단계: 기존 GSShop 매핑 삭제 ===")
        cur.execute(
            "DELETE FROM samba_category_mapping WHERE source_site = 'GSShop'"
        )
        deleted = cur.rowcount
        print(f"  {deleted}건 삭제됨")
        print()

        # 1단계: GSShop 수집 상품의 고유 카테고리 조회 (category4 포함)
        print("=== 1단계: GSShop 카테고리 조회 ===")
        cur.execute("""
            SELECT DISTINCT category, category1, category2, category3, category4
            FROM samba_collected_product
            WHERE source_site = 'GSShop' AND category IS NOT NULL
            LIMIT 20
        """)
        products = cur.fetchall()

        if not products:
            print("GSShop 수집 상품이 없습니다.")
            sys.exit(0)

        print(f"  고유 카테고리 {len(products)}건 조회됨")
        for cat, c1, c2, c3, c4 in products:
            # shipment service와 동일한 방식으로 source_category 구성
            cat_parts = [c1, c2, c3, c4]
            src_cat = " > ".join(c for c in cat_parts if c) or cat or ""
            print(f"  - source_category: {src_cat} (원본: {cat})")
        print()

        # 2단계: 쿠팡 카테고리 트리(cat2) 조회
        print("=== 2단계: 쿠팡 cat2 트리 조회 ===")
        cur.execute(
            "SELECT cat2 FROM samba_category_tree WHERE site_name = 'coupang'"
        )
        row = cur.fetchone()
        if not row or not row[0]:
            print("쿠팡 카테고리 트리(cat2)가 없습니다.")
            sys.exit(1)

        coupang_cat2: dict[str, str] = row[0]
        if isinstance(coupang_cat2, str):
            coupang_cat2 = json.loads(coupang_cat2)
        print(f"  쿠팡 cat2 경로 {len(coupang_cat2)}건 로드됨")
        print()

        # 3단계: 매칭 및 INSERT
        print("=== 3단계: 매칭 및 INSERT ===")
        inserted = 0
        skipped_exists = 0
        skipped_nomatch = 0

        for category, cat1, cat2_val, cat3, cat4 in products:
            # shipment service와 동일하게 category1~4 join
            cat_parts = [cat1, cat2_val, cat3, cat4]
            source_category = " > ".join(c for c in cat_parts if c) or category or ""

            print(f"\n[{source_category}]")

            # 중복 체크 (source_category 기준)
            cur.execute(
                """
                SELECT id FROM samba_category_mapping
                WHERE source_site = 'GSShop' AND source_category = %s
                """,
                (source_category,),
            )
            if cur.fetchone():
                print(f"  SKIP: 이미 매핑 존재")
                skipped_exists += 1
                continue

            # 키워드 매칭 (source_category의 마지막 세그먼트로 매칭)
            matched_code = find_best_match(source_category, coupang_cat2)
            if not matched_code:
                print(f"  SKIP: 매칭 실패 — 수동 매핑 필요")
                skipped_nomatch += 1
                continue

            # INSERT
            now = datetime.now(tz=timezone.utc)
            mapping_id = f"cm_{ULID()}"
            target_mappings = json.dumps({"coupang": matched_code})

            cur.execute(
                """
                INSERT INTO samba_category_mapping
                (id, source_site, source_category, target_mappings, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (mapping_id, "GSShop", source_category, target_mappings, now, now),
            )
            print(f"  INSERT: id={mapping_id}, coupang={matched_code}")
            inserted += 1

        conn.commit()

        # 결과 요약
        print(f"\n=== 결과 ===")
        print(f"  INSERT: {inserted}건")
        print(f"  SKIP(이미존재): {skipped_exists}건")
        print(f"  SKIP(매칭실패): {skipped_nomatch}건")

        # 검증 쿼리
        print(f"\n=== 검증: GSShop 매핑 전체 조회 ===")
        cur.execute(
            """
            SELECT source_category, target_mappings
            FROM samba_category_mapping
            WHERE source_site = 'GSShop'
            ORDER BY created_at
            """
        )
        for row in cur.fetchall():
            mappings = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            print(f"  {row[0]} → coupang:{mappings.get('coupang', 'N/A')}")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
