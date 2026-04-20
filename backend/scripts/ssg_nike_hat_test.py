"""로컬 SSG 나이키 3개 필터 수집 검증 (읽기 전용 probe).

목적: maxDiscount 커밋(2d4335b7)이 실제로 카테고리 오염을 해결하는지
      3개 필터에서 각각 10개 상품을 실제 수집해 category1..4 출력.

사용법:
    cd backend
    .venv/Scripts/python.exe scripts/ssg_nike_hat_test.py

출력: 각 필터별로 상위 10개의 (상품명, category1>category2>category3>category4)
      → 사용자가 육안으로 "볼캡/야구모자", "비니", "남성벨트" 카테고리가
        맞게 오는지 확인.

DB 저장 없음. 프로덕션 접근 없음.
"""

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# backend 패키지 import 경로 설정
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg  # noqa: E402
import httpx  # noqa: E402

from backend.domain.samba.proxy.ssg_sourcing import (  # noqa: E402
    RateLimitError,
    SSGSourcingClient,
)


async def _log_request(request: httpx.Request) -> None:
    print(f"  >> {request.method} {request.url}")


LOCAL_DSN = os.environ.get(
    "LOCAL_DB_DSN",
    "postgresql://test_user:test_password@localhost:5433/test_little_boy",
)

TARGET_FILTER_IDS = [
    "sf_01KPK32GT599RSPWM49MQF518E",  # SSG 나이키 모자_볼캡/야구모자
    "sf_01KPK32H0C6YQ324SAGRAMBDD0",  # SSG 나이키 모자_비니
    "sf_01KPK32H0RHN44M024Z0BDTVDS",  # SSG 나이키 벨트_남성벨트
]

DETAIL_COUNT = 10


def parse_keyword_url(keyword_url: str) -> tuple[str, dict]:
    """worker.py:3245~3292 로직과 동일한 URL → kwargs 변환."""
    kwargs: dict = {}
    keyword = keyword_url
    parsed = urlparse(keyword_url)
    if not parsed.scheme:
        return keyword, kwargs

    qs = parse_qs(parsed.query)
    keyword = qs.get("query", [keyword])[0]

    for k in ("category1Id", "category2Id", "category3Id", "sort", "minPrice", "maxPrice", "maxDiscount"):
        v = qs.get(k, [""])[0]
        if v:
            kwargs[k] = v

    rep_brand_id = qs.get("repBrandId", [""])[0]
    if rep_brand_id:
        kwargs["brand_ids"] = rep_brand_id.split("|")

    ctg_id = qs.get("ctgId", [""])[0]
    if ctg_id:
        kwargs["ctg_id"] = ctg_id
    ctg_lv = qs.get("ctgLv", [""])[0]
    if ctg_lv:
        kwargs["ctg_lv"] = ctg_lv

    return keyword, kwargs


async def test_filter_with_client(
    client: SSGSourcingClient,
    shared: httpx.AsyncClient,
    filter_id: str,
    filter_name: str,
    keyword_url: str,
) -> dict:
    keyword, kwargs = parse_keyword_url(keyword_url)
    print(f"\n{'=' * 78}")
    print(f"[필터] {filter_name}")
    print(f"  filter_id = {filter_id}")
    print(f"  keyword   = {keyword}")
    print(f"  kwargs    = {kwargs}")

    # 검색
    try:
        items = await client.search_products(
            keyword=keyword, page=1, size=40, _shared_client=shared, **kwargs
        )
    except RateLimitError as e:
        print(f"  [!!] SSG 차단: HTTP {e.status} (Retry-After={e.retry_after})")
        return {"filter_id": filter_id, "status": "blocked", "hits": 0, "details": []}
    except Exception as e:
        print(f"  [!!] 검색 실패: {type(e).__name__}: {e}")
        return {"filter_id": filter_id, "status": "error", "hits": 0, "details": []}

    print(f"  검색 결과: {len(items)}건")
    if items:
        print(f"  첫 항목 키: {list(items[0].keys())}")
        for i, it in enumerate(items, 1):
            print(f"    [{i}] {it}")
    if not items:
        return {"filter_id": filter_id, "status": "empty", "hits": 0, "details": []}

    # 상세 수집 (상위 N개)
    details = []
    for i, it in enumerate(items[:DETAIL_COUNT], 1):
        site_pid = it.get("site_product_id") or it.get("id") or ""
        src_name = it.get("name", "")
        try:
            d = await client.get_product_detail(site_pid, _shared_client=shared)
        except RateLimitError as e:
            print(f"  [{i:2}] 차단: {site_pid} (Retry-After={e.retry_after})")
            details.append({"site_pid": site_pid, "name": src_name, "blocked": True})
            continue
        except Exception as e:
            print(f"  [{i:2}] 상세 실패: {site_pid} — {type(e).__name__}: {e}")
            details.append({"site_pid": site_pid, "name": src_name, "error": str(e)})
            continue

        cat_path = " > ".join(
            filter(None, [d.get("category1", ""), d.get("category2", ""), d.get("category3", ""), d.get("category4", "")])
        )
        name = (d.get("name", "") or src_name)[:60]
        print(f"  [{i:2}] {site_pid} {name}")
        print(f"        category: {cat_path}")
        details.append(
            {
                "site_pid": site_pid,
                "name": name,
                "category1": d.get("category1", ""),
                "category2": d.get("category2", ""),
                "category3": d.get("category3", ""),
                "category4": d.get("category4", ""),
            }
        )

    return {
        "filter_id": filter_id,
        "filter_name": filter_name,
        "status": "ok",
        "hits": len(items),
        "details": details,
    }


async def main():
    # 1) 로컬 DB에서 필터 정보 조회
    conn = await asyncpg.connect(LOCAL_DSN)
    try:
        filters = await conn.fetch(
            """
            SELECT id, name, keyword FROM samba_search_filter WHERE id = ANY($1::text[])
            """,
            TARGET_FILTER_IDS,
        )
    finally:
        await conn.close()

    if len(filters) != len(TARGET_FILTER_IDS):
        print(f"[!!] 로컬 DB에서 필터 {len(filters)}/{len(TARGET_FILTER_IDS)}개만 조회됨")
        print("    누락된 ID 확인 필요.")
        for r in filters:
            print(f"    found: {r['id']} {r['name']}")
        return

    # 2) SSG 클라이언트 1개로 3개 필터 순차 실행 (요청 URL 전부 로깅)
    client = SSGSourcingClient()

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        event_hooks={"request": [_log_request]},
    ) as shared:
        results = []
        for r in filters:
            res = await test_filter_with_client(client, shared, r["id"], r["name"], r["keyword"])
            results.append(res)
            await asyncio.sleep(3)

    # 3) 요약
    print(f"\n{'=' * 78}")
    print("[요약]")
    for r in results:
        print(f"  {r.get('filter_name', r['filter_id'])}: status={r['status']}, hits={r['hits']}, 상세={len(r['details'])}")


if __name__ == "__main__":
    asyncio.run(main())
