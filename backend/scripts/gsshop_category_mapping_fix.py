"""GSShop 카테고리 매핑 전수 추가 스크립트.

GSShop 수집 상품의 전체 카테고리를 쿠팡 + 스마트스토어 cat2 트리에서
키워드 매칭하여 samba_category_mapping 테이블에 INSERT/UPDATE한다.

- 기존 매핑이 있으나 target_mappings에 빠진 마켓 키가 있으면 UPDATE
- 매핑 자체가 없으면 양쪽 매칭 후 INSERT

실행:
  cd backend
  source .venv/bin/activate
  python scripts/gsshop_category_mapping_fix.py
"""

import json
import sys
from datetime import datetime, timezone

import psycopg2
from ulid import ULID


# Bug #1: "기타 재화"는 자동 매칭 불가 → 수동 매핑
MANUAL_MAPPINGS: dict[str, dict[str, str]] = {
    "기타 재화": {
        "coupang": "85618",  # 키즈(3~8세) > 남녀공용의류 > 티셔츠 > 공용 라운드티셔츠
        "smartstore": "50000803",  # 여성의류 > 티셔츠 (KC인증 불필요)
    },
}

# Bug #2, #3: 기존 매핑 중 카테고리 코드가 부정확한 것 교정
CORRECT_CODES: dict[str, dict[str, str]] = {
    "패션의류잡화 > 키즈 의류(3~8세) > 남녀공용의류 > 티셔츠": {
        "coupang": "85618",  # 베이비(111688) → 키즈 남녀공용
        "smartstore": "50000803",  # 여성의류 > 티셔츠 (KC인증 불필요)
    },
    "패션의류잡화 > 키즈 의류(3~8세) > 남녀공용의류 > 상하복 세트": {
        "coupang": "70600",  # 여아 정장(85555) → 남녀공용 상하 바지세트
        "smartstore": "50000803",  # 여성의류 > 티셔츠 (KC인증 불필요, 유아동 상하세트도 KC필수)
    },
}


def find_best_match(
    source_category: str,
    cat2_tree: dict[str, str],
) -> str | None:
    """source_category의 마지막 세그먼트를 cat2 경로에서 매칭.

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
    for path, code in cat2_tree.items():
        path_segments = [s.strip() for s in path.split(">")]
        last_segment = path_segments[-1] if path_segments else ""
        if last_segment == keyword:
            return str(code)

    # 2순위: 경로 내 부분일치
    candidates: list[tuple[str, str]] = []
    for path, code in cat2_tree.items():
        if keyword in path:
            candidates.append((path, str(code)))

    if candidates:
        # 경로가 가장 짧은(더 구체적인) 후보 선택
        best = min(candidates, key=lambda x: len(x[0]))
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
        # 1단계: GSShop 수집 상품의 전체 고유 카테고리 조회 (LIMIT 없음)
        print("=== 1단계: GSShop 카테고리 전수 조회 ===")
        cur.execute("""
            SELECT DISTINCT category, category1, category2, category3, category4
            FROM samba_collected_product
            WHERE source_site = 'GSShop' AND category IS NOT NULL
        """)
        products = cur.fetchall()

        if not products:
            print("GSShop 수집 상품이 없습니다.")
            sys.exit(0)

        # source_category 구성 (shipment service 동일 방식)
        unique_categories: list[str] = []
        for category, cat1, cat2_val, cat3, cat4 in products:
            cat_parts = [cat1, cat2_val, cat3, cat4]
            src_cat = " > ".join(c for c in cat_parts if c) or category or ""
            if src_cat and src_cat not in unique_categories:
                unique_categories.append(src_cat)

        print(f"  고유 카테고리 {len(unique_categories)}건 조회됨")
        for sc in unique_categories:
            print(f"  - {sc}")
        print()

        # 2단계: 기존 GSShop 매핑 조회
        print("=== 2단계: 기존 GSShop 매핑 조회 ===")
        cur.execute("""
            SELECT id, source_category, target_mappings
            FROM samba_category_mapping
            WHERE source_site = 'GSShop'
        """)
        existing_mappings: dict[str, tuple[str, dict]] = {}
        for row in cur.fetchall():
            mapping_id = row[0]
            src_cat = row[1]
            tm = row[2] if isinstance(row[2], dict) else json.loads(row[2])
            existing_mappings[src_cat] = (mapping_id, tm)
        print(f"  기존 매핑 {len(existing_mappings)}건")
        for sc, (mid, tm) in existing_mappings.items():
            print(f"  - {sc} → {list(tm.keys())}")
        print()

        # 3단계: 쿠팡 + 스마트스토어 cat2 트리 로드
        print("=== 3단계: 카테고리 트리 로드 ===")
        cur.execute(
            "SELECT site_name, cat2 FROM samba_category_tree WHERE site_name IN ('coupang', 'smartstore')"
        )
        cat2_trees: dict[str, dict[str, str]] = {}
        for row in cur.fetchall():
            site_name = row[0]
            tree = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            cat2_trees[site_name] = tree
            print(f"  {site_name}: {len(tree)}건 로드됨")

        if "coupang" not in cat2_trees:
            print("쿠팡 카테고리 트리가 없습니다.")
            sys.exit(1)
        if "smartstore" not in cat2_trees:
            print("스마트스토어 카테고리 트리가 없습니다.")
            sys.exit(1)
        print()

        # 3.5단계: 기존 매핑 코드 교정 (CORRECT_CODES)
        print("=== 3.5단계: 기존 매핑 코드 교정 ===")
        corrected = 0
        for src_cat, correct_targets in CORRECT_CODES.items():
            if src_cat in existing_mappings:
                mapping_id, current_targets = existing_mappings[src_cat]
                merged = {**current_targets, **correct_targets}
                if merged != current_targets:
                    now = datetime.now(tz=timezone.utc)
                    cur.execute(
                        """
                        UPDATE samba_category_mapping
                        SET target_mappings = %s, updated_at = %s
                        WHERE id = %s
                        """,
                        (json.dumps(merged), now, mapping_id),
                    )
                    print(f"  CORRECT: [{src_cat}]")
                    for k, v in correct_targets.items():
                        old_v = current_targets.get(k, "N/A")
                        print(f"    {k}: {old_v} → {v}")
                    # 교정된 값을 existing_mappings에도 반영
                    existing_mappings[src_cat] = (mapping_id, merged)
                    corrected += 1
                else:
                    print(f"  SKIP: [{src_cat}] 이미 올바른 코드")
            else:
                print(f"  N/A: [{src_cat}] 기존 매핑 없음 (4단계에서 처리)")
        print(f"  교정 완료: {corrected}건\n")

        # 4단계: 매칭 및 INSERT/UPDATE
        print("=== 4단계: 매칭 및 INSERT/UPDATE ===")
        inserted = 0
        updated = 0
        skipped_complete = 0
        failed: list[str] = []

        for source_category in unique_categories:
            print(f"\n[{source_category}]")

            # 수동 매핑 우선 체크
            if source_category in MANUAL_MAPPINGS:
                manual = MANUAL_MAPPINGS[source_category]
                coupang_code = manual.get("coupang")
                smartstore_code = manual.get("smartstore")
                print(
                    f"  수동 매핑 적용: coupang={coupang_code}, smartstore={smartstore_code}"
                )
            else:
                # 자동 매칭
                coupang_code = find_best_match(source_category, cat2_trees["coupang"])
                smartstore_code = find_best_match(
                    source_category, cat2_trees["smartstore"]
                )

            if not coupang_code and not smartstore_code:
                print(f"  SKIP: 양쪽 매칭 실패 — 수동 매핑 필요")
                failed.append(source_category)
                continue

            new_targets: dict[str, str] = {}
            if coupang_code:
                new_targets["coupang"] = coupang_code
            if smartstore_code:
                new_targets["smartstore"] = smartstore_code

            if source_category in existing_mappings:
                # 기존 매핑 존재 → 빠진 마켓 키 업데이트
                mapping_id, current_targets = existing_mappings[source_category]
                merged = {**current_targets, **new_targets}

                if merged == current_targets:
                    print(
                        f"  SKIP: 이미 완전한 매핑 존재 ({list(current_targets.keys())})"
                    )
                    skipped_complete += 1
                    continue

                now = datetime.now(tz=timezone.utc)
                cur.execute(
                    """
                    UPDATE samba_category_mapping
                    SET target_mappings = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (json.dumps(merged), now, mapping_id),
                )
                added_keys = set(merged.keys()) - set(current_targets.keys())
                print(f"  UPDATE: id={mapping_id}, 추가된 키={added_keys}")
                updated += 1
            else:
                # 신규 INSERT
                now = datetime.now(tz=timezone.utc)
                mapping_id = f"cm_{ULID()}"
                cur.execute(
                    """
                    INSERT INTO samba_category_mapping
                    (id, source_site, source_category, target_mappings, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        mapping_id,
                        "GSShop",
                        source_category,
                        json.dumps(new_targets),
                        now,
                        now,
                    ),
                )
                print(f"  INSERT: id={mapping_id}, targets={list(new_targets.keys())}")
                inserted += 1

        conn.commit()

        # 결과 요약
        print(f"\n{'=' * 50}")
        print(f"=== 결과 ===")
        print(f"  CORRECT(코드교정): {corrected}건")
        print(f"  INSERT(신규): {inserted}건")
        print(f"  UPDATE(키추가): {updated}건")
        print(f"  SKIP(완전매핑): {skipped_complete}건")
        print(f"  FAIL(매칭실패): {len(failed)}건")

        if failed:
            print(f"\n=== 매칭 실패 카테고리 (수동 매핑 필요) ===")
            for fc in failed:
                print(f"  - {fc}")

        # 검증: 전체 GSShop 매핑 조회
        print(f"\n=== 검증: GSShop 매핑 전체 조회 ===")
        cur.execute("""
            SELECT source_category, target_mappings
            FROM samba_category_mapping
            WHERE source_site = 'GSShop'
            ORDER BY created_at
        """)
        for row in cur.fetchall():
            mappings = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            coupang_val = mappings.get("coupang", "N/A")
            ss_val = mappings.get("smartstore", "N/A")
            print(f"  {row[0]} → coupang:{coupang_val}, smartstore:{ss_val}")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
