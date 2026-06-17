"""SSG 카테고리 필터 전수조사 및 수정 스크립트.

문제: SSG 수집 시 resultItemObj에 dispCtgLclsNm/MclsNm이 없는 케이스에서
     leaf 1개만 저장 → 필터명이 "SSG_브랜드_머플러" 형태로 잘못 생성.

수정 전략:
1. SSG /common/0.1/displayCategory.ssg API로 전체 카테고리 코드→경로 맵 생성
2. 잘못된 필터의 category_filter 코드로 경로 역조회
3. 같은 category_filter 코드를 가진 올바른 필터 DB 역조회
4. 상품 category 필드 직접 파싱 (이미 올바른 상품이 있는 경우)
5. SSG 상세 API 재호출 (rate limit 60s — 최후 수단)

사용법:
  python scripts/fix_ssg_category_filters.py          # 조회만
  python scripts/fix_ssg_category_filters.py --fix    # 실제 수정
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncpg
from backend.core.config import settings


async def _build_ctg_code_map(conn) -> dict[str, str]:
    """SSG 카테고리 API로 {dispCtgId → '대 > 중 > 소'} 맵 생성.
    실패 시 빈 dict 반환.
    """
    from backend.domain.samba.proxy.ssg import SSGClient

    # DB에서 SSG 계정 api_key 조회
    rows = await conn.fetch(
        """
        SELECT additional_fields, api_key
        FROM samba_market_account
        WHERE market_type = 'ssg' AND is_active = true
        LIMIT 5
        """
    )
    if not rows:
        print("  [카테고리맵] SSG 계정 없음 → 카테고리 API 우회 불가")
        return {}

    for row in rows:
        import json
        extra = {}
        if row["additional_fields"]:
            try:
                extra = json.loads(row["additional_fields"]) if isinstance(row["additional_fields"], str) else row["additional_fields"]
            except Exception:
                pass
        api_key = extra.get("apiKey") or row["api_key"] or ""
        store_id = extra.get("storeId") or "6004"
        if not api_key:
            continue

        try:
            client = SSGClient(api_key=api_key, site_no=store_id)
            code_map: dict[str, str] = {}
            page = 1
            while True:
                raw = await client.get_display_categories_all(
                    site_no=store_id, page=page, page_size=500
                )
                result_obj = raw.get("result", {}) or {}
                display_categorys = result_obj.get("displayCategorys", [])
                items: list = []
                if isinstance(display_categorys, list):
                    for wrapper in display_categorys:
                        if isinstance(wrapper, dict):
                            cat = wrapper.get("category", [])
                            if isinstance(cat, list):
                                items.extend(cat)
                            elif isinstance(cat, dict):
                                items.append(cat)

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    cat_id = str(item.get("dispCtgId") or "")
                    path = item.get("dispCtgPathNm", "") or item.get("dispCtgNm", "")
                    if cat_id and path:
                        normalized = " > ".join(
                            seg.strip() for seg in path.split(">") if seg.strip()
                        )
                        code_map[cat_id] = normalized

                if len(items) < 500:
                    break
                page += 1

            print(f"  [카테고리맵] {len(code_map)}개 코드 로드 (api_key={api_key[:8]}...)")
            return code_map
        except Exception as e:
            print(f"  [카테고리맵] API 실패: {e}")
            continue

    return {}


async def main(do_fix: bool = False):
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl="require" if settings.use_db_ssl else False,
    )
    try:
        rows = await conn.fetch(
            """
            SELECT
                f.id,
                f.name,
                f.source_site,
                f.category_filter,
                f.tenant_id,
                f.parent_id,
                (SELECT COUNT(*) FROM samba_collected_product
                 WHERE search_filter_id = f.id) AS product_count
            FROM samba_search_filter f
            WHERE f.source_site = 'SSG'
              AND f.name IS NOT NULL
              AND array_length(string_to_array(f.name, '_'), 1) <= 3
            ORDER BY product_count DESC, f.name
            """
        )

        if not rows:
            print("잘못된 SSG 필터 없음.")
            return

        print(f"\n[전수조사] 카테고리 1단계 SSG 필터 {len(rows)}개:\n")
        for r in rows:
            print(
                f"  [{r['product_count']}건] {r['name']} "
                f"(id={r['id'][:8]}... ctg_filter={r['category_filter']})"
            )

        if not do_fix:
            print("\n--fix 없이 조회만 실행. 수정하려면 --fix 플래그 추가.")
            return

        # 0순위: SSG 전체 카테고리 코드→경로 맵 생성 (API 1회 호출)
        ctg_code_map = await _build_ctg_code_map(conn)

        # 올바른 SSG 필터(4단계 이상) 전체 로드 — category_filter 코드로 역조회용
        good_filters = await conn.fetch(
            """
            SELECT name, category_filter
            FROM samba_search_filter
            WHERE source_site = 'SSG'
              AND name IS NOT NULL
              AND array_length(string_to_array(name, '_'), 1) >= 4
              AND category_filter IS NOT NULL
            """
        )
        # {category_filter_code: name} 맵
        good_map: dict[str, str] = {}
        for gf in good_filters:
            code = gf["category_filter"]
            if code and code not in good_map:
                good_map[code] = gf["name"]

        print(f"\n[FIX] 올바른 필터 {len(good_map)}개 로드. 교정 시작...\n")

        from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

        client = SSGSourcingClient()

        for r in rows:
            filter_id = r["id"]
            old_name = r["name"]
            product_count = r["product_count"]
            ctg_code = r["category_filter"]

            if product_count == 0:
                print(f"  SKIP {old_name} (상품 0건)")
                continue

            # 브랜드명 추출 (name 형식: SSG_브랜드_카테고리)
            name_parts = old_name.split("_")
            brand_nm = name_parts[1] if len(name_parts) >= 2 else "브랜드"

            new_name = None
            new_cat_str = None
            source = ""

            # 0순위: 카테고리 API 맵에서 코드 직접 역조회
            if ctg_code and ctg_code in ctg_code_map:
                full_path = ctg_code_map[ctg_code]
                cat_parts = [p.strip() for p in full_path.split(" > ") if p.strip()]
                if len(cat_parts) >= 2:
                    new_name = (f"SSG_{brand_nm}_" + "_".join(cat_parts)).replace(
                        "/", "_"
                    )
                    new_cat_str = full_path
                    source = f"카테고리API(ctgId={ctg_code})"

            # 1순위: 같은 category_filter 코드를 가진 올바른 필터 역조회
            if not new_name:
                if ctg_code and ctg_code in good_map:
                    ref_name = good_map[ctg_code]
                    ref_parts = ref_name.split("_")
                    if len(ref_parts) >= 4:
                        cat_parts = ref_parts[2:]
                        new_name = (f"SSG_{brand_nm}_" + "_".join(cat_parts)).replace(
                            "/", "_"
                        )
                        new_cat_str = " > ".join(cat_parts)
                        source = f"DB역조회({ref_name})"

            # 2순위: 해당 필터 상품의 기존 category 필드가 올바른 경우
            if not new_name:
                sample_cats = await conn.fetch(
                    """
                    SELECT DISTINCT category
                    FROM samba_collected_product
                    WHERE search_filter_id = $1
                      AND category IS NOT NULL
                      AND category LIKE '% > %'
                    LIMIT 1
                    """,
                    filter_id,
                )
                if sample_cats:
                    existing_cat = sample_cats[0]["category"]
                    cat_parts = [
                        p.strip() for p in existing_cat.split(" > ") if p.strip()
                    ]
                    if len(cat_parts) >= 2:
                        new_name = (f"SSG_{brand_nm}_" + "_".join(cat_parts)).replace(
                            "/", "_"
                        )
                        new_cat_str = existing_cat
                        source = f"상품category직접({existing_cat})"

            # 3순위: SSG 상세 API 재호출 (최후 수단)
            if not new_name:
                sample = await conn.fetchrow(
                    """
                    SELECT site_product_id
                    FROM samba_collected_product
                    WHERE search_filter_id = $1
                      AND site_product_id IS NOT NULL
                    LIMIT 1
                    """,
                    filter_id,
                )
                if sample:
                    spid = sample["site_product_id"]
                    try:
                        detail = await client.get_product_detail(spid)
                        cat1 = detail.get("category1", "") or ""
                        cat2 = detail.get("category2", "") or ""
                        cat3 = detail.get("category3", "") or ""
                        cat_parts = [p for p in [cat1, cat2, cat3] if p]
                        if cat_parts:
                            new_name = (
                                f"SSG_{brand_nm}_" + "_".join(cat_parts)
                            ).replace("/", "_")
                            new_cat_str = " > ".join(cat_parts)
                            source = f"API재호출(spid={spid})"
                    except Exception as e:
                        print(f"  ERR  {old_name} API재호출 실패: {e}")

            if not new_name or not new_cat_str:
                print(f"  SKIP {old_name} (카테고리 정보 없음)")
                continue

            if new_name == old_name:
                print(f"  SAME {old_name}")
                continue

            print(f"  FIX  {old_name}")
            print(f"    → {new_name}  [{source}]")
            print(f"    category='{new_cat_str}' ({product_count}건)")

            await conn.execute(
                "UPDATE samba_search_filter SET name = $1 WHERE id = $2",
                new_name,
                filter_id,
            )
            updated = await conn.execute(
                "UPDATE samba_collected_product SET category = $1 WHERE search_filter_id = $2",
                new_cat_str,
                filter_id,
            )
            print(f"    상품 업데이트: {updated}")

        print("\n[완료]")

    finally:
        await conn.close()


if __name__ == "__main__":
    do_fix = "--fix" in sys.argv
    asyncio.run(main(do_fix=do_fix))
