"""GSShop → 스마트스토어 전송 준비 스크립트.

GSShop 수집 상품의 market_enabled에 smartstore 추가 +
카테고리 매핑에 smartstore 키 추가.

기존 insert_gsshop_coupang_mapping.py 패턴을 재사용하여
스마트스토어 cat2 트리에서 키워드 매칭한다.

실행:
  cd backend
  source .venv/bin/activate
  python scripts/gsshop_smartstore_prepare.py
"""

import json
import sys
from datetime import datetime, timezone

import psycopg2
from ulid import ULID


def find_best_match(
    source_category: str,
    smartstore_cat2: dict[str, str],
) -> str | None:
    """source_category의 마지막 세그먼트를 스마트스토어 cat2 경로에서 매칭.

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
    for path, code in smartstore_cat2.items():
        path_segments = [s.strip() for s in path.split(">")]
        last_segment = path_segments[-1] if path_segments else ""
        if last_segment == keyword:
            print(f"  [완전일치] '{keyword}' → {path} (코드: {code})")
            return str(code)

    # 2순위: 경로 내 부분일치
    candidates: list[tuple[str, str]] = []
    for path, code in smartstore_cat2.items():
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
        # ============================================================
        # Step 1: market_enabled에 smartstore 추가
        # ============================================================
        print("=== Step 1: market_enabled 업데이트 ===")
        cur.execute("""
            UPDATE samba_collected_product
            SET market_enabled =
              CASE
                WHEN market_enabled IS NULL
                  THEN '{"coupang":true,"smartstore":true}'::json
                ELSE (market_enabled::text::jsonb || '{"smartstore":true}'::jsonb)::json
              END
            WHERE source_site = 'GSShop'
        """)
        market_updated = cur.rowcount
        print(f"  {market_updated}건 market_enabled 업데이트됨")
        print()

        # ============================================================
        # Step 2: 기존 GSShop 카테고리 매핑 조회
        # ============================================================
        print("=== Step 2: 기존 GSShop 카테고리 매핑 조회 ===")
        cur.execute("""
            SELECT id, source_category, target_mappings
            FROM samba_category_mapping
            WHERE source_site = 'GSShop'
        """)
        existing_mappings = cur.fetchall()
        print(f"  기존 매핑 {len(existing_mappings)}건 조회됨")

        # 이미 smartstore 매핑이 있는지 확인
        already_has_smartstore = 0
        needs_smartstore: list[tuple[str, str, dict]] = []  # (id, source_category, target_mappings)
        for row in existing_mappings:
            mapping_id, source_cat, target_map = row
            if isinstance(target_map, str):
                target_map = json.loads(target_map)
            if "smartstore" in target_map:
                already_has_smartstore += 1
            else:
                needs_smartstore.append((mapping_id, source_cat, target_map))

        print(f"  이미 smartstore 있음: {already_has_smartstore}건")
        print(f"  smartstore 추가 필요: {len(needs_smartstore)}건")
        print()

        # ============================================================
        # Step 3: 스마트스토어 카테고리 트리(cat2) 로드
        # ============================================================
        print("=== Step 3: 스마트스토어 cat2 트리 조회 ===")
        cur.execute(
            "SELECT cat2 FROM samba_category_tree WHERE site_name = 'smartstore'"
        )
        row = cur.fetchone()
        if not row or not row[0]:
            print("ERROR: 스마트스토어 카테고리 트리(cat2)가 없습니다.")
            sys.exit(1)

        smartstore_cat2: dict[str, str] = row[0]
        if isinstance(smartstore_cat2, str):
            smartstore_cat2 = json.loads(smartstore_cat2)
        print(f"  스마트스토어 cat2 경로 {len(smartstore_cat2)}건 로드됨")
        print()

        # ============================================================
        # Step 4: 기존 매핑에 smartstore 키 추가 (UPDATE)
        # ============================================================
        print("=== Step 4: 기존 매핑에 smartstore 추가 ===")
        updated = 0
        match_failed_existing: list[str] = []

        for mapping_id, source_cat, target_map in needs_smartstore:
            print(f"\n[{source_cat}]")
            matched_code = find_best_match(source_cat, smartstore_cat2)
            if not matched_code:
                print(f"  SKIP: 매칭 실패 — 수동 매핑 필요")
                match_failed_existing.append(source_cat)
                continue

            # target_mappings에 smartstore 키 추가
            target_map["smartstore"] = matched_code
            new_target = json.dumps(target_map)
            cur.execute(
                """
                UPDATE samba_category_mapping
                SET target_mappings = %s, updated_at = %s
                WHERE id = %s
                """,
                (new_target, datetime.now(tz=timezone.utc), mapping_id),
            )
            print(f"  UPDATE: smartstore={matched_code}")
            updated += 1

        print(f"\n  업데이트: {updated}건")
        print(f"  매칭실패: {len(match_failed_existing)}건")
        print()

        # ============================================================
        # Step 5: 매핑이 없는 GSShop 카테고리에 새로 INSERT
        # ============================================================
        print("=== Step 5: 매핑 없는 카테고리 INSERT ===")

        # 기존 매핑의 source_category 집합
        existing_source_cats = {row[1] for row in existing_mappings}

        # GSShop 수집 상품의 고유 카테고리 조회
        cur.execute("""
            SELECT DISTINCT category, category1, category2, category3, category4
            FROM samba_collected_product
            WHERE source_site = 'GSShop' AND category IS NOT NULL
        """)
        all_products = cur.fetchall()

        inserted = 0
        match_failed_new: list[str] = []

        for category, cat1, cat2_val, cat3, cat4 in all_products:
            cat_parts = [cat1, cat2_val, cat3, cat4]
            source_category = " > ".join(c for c in cat_parts if c) or category or ""

            if source_category in existing_source_cats:
                continue  # 이미 매핑 존재

            print(f"\n[{source_category}] (신규)")

            # 스마트스토어 + 쿠팡 둘 다 매칭 시도
            ss_code = find_best_match(source_category, smartstore_cat2)

            # 쿠팡 cat2도 로드하여 함께 매핑
            cur.execute(
                "SELECT cat2 FROM samba_category_tree WHERE site_name = 'coupang'"
            )
            coupang_row = cur.fetchone()
            coupang_cat2: dict[str, str] = {}
            if coupang_row and coupang_row[0]:
                coupang_cat2 = coupang_row[0]
                if isinstance(coupang_cat2, str):
                    coupang_cat2 = json.loads(coupang_cat2)

            cp_code = find_best_match(source_category, coupang_cat2)

            if not ss_code and not cp_code:
                print(f"  SKIP: 매칭 실패 — 수동 매핑 필요")
                match_failed_new.append(source_category)
                continue

            target_mappings_dict: dict[str, str] = {}
            if cp_code:
                target_mappings_dict["coupang"] = cp_code
            if ss_code:
                target_mappings_dict["smartstore"] = ss_code

            now = datetime.now(tz=timezone.utc)
            new_id = f"cm_{ULID()}"
            cur.execute(
                """
                INSERT INTO samba_category_mapping
                (id, source_site, source_category, target_mappings, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (new_id, "GSShop", source_category, json.dumps(target_mappings_dict), now, now),
            )
            print(f"  INSERT: id={new_id}, mappings={target_mappings_dict}")
            inserted += 1
            existing_source_cats.add(source_category)

        print(f"\n  신규 INSERT: {inserted}건")
        print(f"  매칭실패: {len(match_failed_new)}건")
        print()

        conn.commit()

        # ============================================================
        # Step 6: 전송 가능 상품 수 확인
        # ============================================================
        print("=== Step 6: 전송 가능 상품 수 확인 ===")

        # market_enabled에 smartstore 있는 상품 수
        cur.execute("""
            SELECT COUNT(*)
            FROM samba_collected_product
            WHERE source_site = 'GSShop'
              AND market_enabled::text LIKE '%%smartstore%%'
        """)
        ss_enabled = cur.fetchone()[0]
        print(f"  market_enabled에 smartstore 있는 상품: {ss_enabled}건")

        # smartstore 카테고리 매핑이 있는 카테고리 수
        cur.execute("""
            SELECT COUNT(*)
            FROM samba_category_mapping
            WHERE source_site = 'GSShop'
              AND target_mappings::text LIKE '%%smartstore%%'
        """)
        ss_mapped = cur.fetchone()[0]
        print(f"  smartstore 카테고리 매핑: {ss_mapped}건")

        # 실제 전송 가능 상품 수 (카테고리 매핑과 조인)
        cur.execute("""
            SELECT COUNT(*)
            FROM samba_collected_product p
            WHERE p.source_site = 'GSShop'
              AND p.market_enabled::text LIKE '%%smartstore%%'
              AND EXISTS (
                SELECT 1 FROM samba_category_mapping cm
                WHERE cm.source_site = 'GSShop'
                  AND cm.target_mappings::text LIKE '%%smartstore%%'
                  AND cm.source_category = (
                    COALESCE(
                      NULLIF(
                        CONCAT_WS(' > ',
                          NULLIF(p.category1, ''),
                          NULLIF(p.category2, ''),
                          NULLIF(p.category3, ''),
                          NULLIF(p.category4, '')
                        ), ''
                      ),
                      p.category
                    )
                  )
              )
        """)
        transmittable = cur.fetchone()[0]
        print(f"  실제 전송 가능 상품: {transmittable}건")
        print()

        # ============================================================
        # 결과 요약
        # ============================================================
        print("=" * 60)
        print("=== 최종 결과 요약 ===")
        print("=" * 60)
        print(f"  market_enabled 업데이트: {market_updated}건")
        print(f"  기존 매핑 smartstore 추가(UPDATE): {updated}건")
        print(f"  신규 매핑 INSERT: {inserted}건")
        print(f"  전송 가능 상품: {transmittable}건")

        # 매칭 실패 목록
        all_failed = match_failed_existing + match_failed_new
        if all_failed:
            print(f"\n  ⚠ 매칭 실패 카테고리 ({len(all_failed)}건):")
            for cat in all_failed:
                print(f"    - {cat}")

        # 검증: GSShop 매핑 전체 조회
        print(f"\n=== 검증: GSShop 매핑 전체 조회 ===")
        cur.execute("""
            SELECT source_category, target_mappings
            FROM samba_category_mapping
            WHERE source_site = 'GSShop'
            ORDER BY created_at
        """)
        for row in cur.fetchall():
            mappings = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            cp = mappings.get("coupang", "N/A")
            ss = mappings.get("smartstore", "N/A")
            print(f"  {row[0]} → coupang:{cp}, smartstore:{ss}")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
