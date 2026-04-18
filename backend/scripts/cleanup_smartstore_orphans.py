"""스마트스토어 고아 상품 정리 스크립트.

DB에 연결 없는(market_product_nos 없음) Naver 등록 상품을 찾아 삭제한다.

사용법:
    cd backend
    # dry-run (삭제 없이 목록만 출력)
    python scripts/cleanup_smartstore_orphans.py

    # 실제 삭제
    python scripts/cleanup_smartstore_orphans.py --delete
"""

import argparse
import asyncio
import sys

sys.path.insert(0, ".")

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_write_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.collector.model import SambaCollectedProduct
from backend.domain.samba.proxy.smartstore import SmartStoreClient


async def fetch_all_naver_products(client: SmartStoreClient) -> list[dict]:
    """Naver에 등록된 전체 상품 목록을 페이징으로 수집."""
    all_products = []
    page = 1
    page_size = 100
    while True:
        result = await client._call_api(
            "POST",
            "/v1/products/search",
            body={"page": page, "size": page_size},
        )
        contents = result.get("contents") or result.get("data") or []
        if isinstance(result, list):
            contents = result
        if not contents:
            break
        all_products.extend(contents)
        total_count = result.get("totalCount") or result.get("total") or 0
        print(f"  수집 중: {len(all_products)} / {total_count or '?'} (page {page})")
        if len(contents) < page_size:
            break
        if total_count and len(all_products) >= total_count:
            break
        page += 1
    return all_products


async def run(delete: bool) -> None:
    async with get_write_session() as session:
        session: AsyncSession

        # 스마트스토어 계정 전체 조회
        result = await session.exec(
            select(SambaMarketAccount).where(
                SambaMarketAccount.market_type == "smartstore",
                SambaMarketAccount.is_active == True,  # noqa: E712
            )
        )
        accounts = result.all()
        if not accounts:
            print("활성 스마트스토어 계정 없음")
            return

        # DB에 기록된 모든 origin product no 수집
        prod_result = await session.exec(
            select(SambaCollectedProduct).where(
                SambaCollectedProduct.market_product_nos.isnot(None)
            )
        )
        all_products = prod_result.all()

        db_origin_nos: set[str] = set()
        for p in all_products:
            nos = p.market_product_nos or {}
            for k, v in nos.items():
                if not k.endswith("_origin"):
                    continue
                if isinstance(v, str) and v:
                    db_origin_nos.add(v)
                elif isinstance(v, dict):
                    o = v.get("originProductNo") or v.get("productNo") or ""
                    if o:
                        db_origin_nos.add(str(o))

            # channel no (account_id 키) 도 추가 — origin 키 없는 계정 대비
            for k, v in nos.items():
                if k.endswith("_origin"):
                    continue
                if isinstance(v, str) and v:
                    db_origin_nos.add(v)

        print(f"\nDB 등록 상품번호: {len(db_origin_nos):,}개")

        total_orphans = 0
        for account in accounts:
            add_info = account.additional_fields or {}
            client_id = add_info.get("clientId") or account.api_key or ""
            client_secret = add_info.get("clientSecret") or account.api_secret or ""
            if not client_id or not client_secret:
                print(f"\n[{account.id}] API 키 없음 — 스킵")
                continue

            print(f"\n[계정: {account.id}] Naver 상품 수집 중...")
            client = SmartStoreClient(client_id, client_secret)
            naver_products = await fetch_all_naver_products(client)
            print(f"  Naver 등록 총 {len(naver_products):,}개")

            orphans = []
            for np in naver_products:
                origin_no = str(
                    np.get("originProductNo")
                    or np.get("originProduct", {}).get("id", "")
                    or ""
                )
                channel_nos = [
                    str(cp.get("channelProductNo", ""))
                    for cp in np.get("channelProducts", [])
                    if cp.get("channelProductNo")
                ]
                in_db = (origin_no and origin_no in db_origin_nos) or any(
                    cn in db_origin_nos for cn in channel_nos
                )
                if not in_db and origin_no:
                    name = (
                        np.get("originProduct", {}).get("name")
                        or np.get("name", "")
                        or "(이름 없음)"
                    )
                    orphans.append({"origin_no": origin_no, "name": name})

            print(f"  고아 상품: {len(orphans):,}개")
            total_orphans += len(orphans)

            for o in orphans:
                print(f"  - {o['origin_no']}  {o['name'][:60]}")

            if delete and orphans:
                print("\n  삭제 시작...")
                deleted = 0
                for o in orphans:
                    try:
                        await client.delete_product(o["origin_no"])
                        print(f"  삭제 완료: {o['origin_no']}")
                        deleted += 1
                    except Exception as e:
                        print(f"  삭제 실패: {o['origin_no']} — {e}")
                print(f"  삭제 완료: {deleted}/{len(orphans)}개")

        print(f"\n===== 총 고아 상품: {total_orphans:,}개 =====")
        if not delete:
            print("dry-run 완료. 실제 삭제하려면 --delete 옵션 추가")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--delete", action="store_true", help="실제 삭제 실행 (없으면 dry-run)"
    )
    args = parser.parse_args()

    if args.delete:
        print("=== 실제 삭제 모드 ===")
    else:
        print("=== dry-run 모드 (삭제 없음) ===")

    asyncio.run(run(delete=args.delete))
