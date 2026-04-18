"""롯데ON 즉시할인 일괄 종료 스크립트 (1회성, PR #39 머지 후 실행)

PR #35~#38 기간 즉시할인 25%가 활성화된 채 등록된 상품의 행사를 일괄 종료.

실행 방법:
  cd backend
  LOTTEON_API_KEY=xxx uv run python scripts/_tmp_lotteon_clean_immediate_discount.py

주의:
- 롯데ON API 응답 구조(키명)는 첫 실행 시 출력으로 확인 후 조정 필요
- 즉시할인 행사가 없는 상품은 자동 스킵됨
- 완료 후 이 파일은 삭제해도 됨
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.domain.samba.proxy.lotteon import LotteonClient

API_KEY = os.environ.get("LOTTEON_API_KEY", "")


async def main() -> None:
    if not API_KEY:
        print("ERROR: LOTTEON_API_KEY 환경변수를 설정하세요.")
        sys.exit(1)

    client = LotteonClient(api_key=API_KEY)
    await client.test_auth()
    print(f"인증 완료 — trNo={client.tr_no}")

    page = 1
    total_checked = 0
    terminated = 0
    errors = 0

    while True:
        result = await client.list_registered_products(page=page, size=100)

        # 응답 구조 확인용 (첫 페이지만 출력)
        if page == 1:
            print(
                f"[DEBUG] list_registered_products 응답 최상위 키: {list(result.keys())}"
            )
            data = result.get("data", result)
            print(
                f"[DEBUG] data 키: {list(data.keys()) if isinstance(data, dict) else type(data)}"
            )

        data = result.get("data", {})
        products = (
            data.get("productList") or data.get("list") or data.get("items") or []
        )

        if not products:
            print(f"p{page}: 상품 없음 — 종료")
            break

        print(f"p{page}: {len(products)}건 처리 중...")

        for prod in products:
            spd_no = prod.get("spdNo") or prod.get("spd_no") or ""
            if not spd_no:
                continue

            total_checked += 1

            try:
                disc_result = await client.search_immediate_discount_list(spd_no)
                disc_data = disc_result.get("data", {})
                pr_list = (
                    disc_data.get("prList")
                    or disc_data.get("immediateDiscountList")
                    or disc_data.get("list")
                    or []
                )

                for pr in pr_list:
                    awy_no = pr.get("awyDcPdRegNo") or pr.get("prNo") or ""
                    if not awy_no:
                        continue
                    try:
                        await client.terminate_immediate_discount(spd_no, awy_no)
                        terminated += 1
                        print(f"  [완료] {spd_no} / {awy_no}")
                    except Exception as e:
                        errors += 1
                        print(f"  [오류] {spd_no} / {awy_no}: {e}")

            except Exception as e:
                errors += 1
                print(f"  [오류] {spd_no} 조회 실패: {e}")

        page += 1

    print(
        f"\n=== 완료: 확인 {total_checked}건, 종료 {terminated}건, 오류 {errors}건 ==="
    )


if __name__ == "__main__":
    asyncio.run(main())
