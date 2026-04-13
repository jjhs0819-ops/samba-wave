"""PlayAuto EMP API 가격 수정 직접 테스트.

Usage:
    python test_playauto_price.py <API_KEY> <MASTER_CODE> <NEW_PRICE> <NEW_COST>

Example:
    python test_playauto_price.py "abc123..." "MC12345" 142000 83940
"""

import asyncio
import sys
import json
import httpx

EMP_BASE_URL = "https://playauto-api.playauto.co.kr/emp/v1"


async def main():
    if len(sys.argv) < 5:
        print(
            "Usage: python test_playauto_price.py <API_KEY> <MASTER_CODE> <NEW_PRICE> <NEW_COST>"
        )
        sys.exit(1)

    api_key = sys.argv[1]
    master_code = sys.argv[2]
    new_price = sys.argv[3]
    new_cost = sys.argv[4]

    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1: GET - 현재 상품 조회
        print("=" * 50)
        print("[STEP 1] 현재 상품 조회")
        resp = await client.get(
            f"{EMP_BASE_URL}/prods",
            headers=headers,
            params={"MasterCode": master_code},
        )
        print(f"Status: {resp.status_code}")
        data = resp.json()
        if isinstance(data, list) and data:
            prod = data[0] if isinstance(data[0], dict) else data
        elif isinstance(data, dict):
            prod = data
        else:
            prod = data

        # 현재 가격 정보만 추출
        if isinstance(prod, dict):
            print(f"  ProdName: {prod.get('ProdName', 'N/A')[:50]}")
            print(f"  Price (판매가): {prod.get('Price', 'N/A')}")
            print(f"  CostPrice (원가): {prod.get('CostPrice', 'N/A')}")
            print(f"  StreetPrice (시중가): {prod.get('StreetPrice', 'N/A')}")
            print(f"  Count (재고): {prod.get('Count', 'N/A')}")
        else:
            print(f"  Raw: {json.dumps(data, ensure_ascii=False)[:200]}")

        # Step 2: PATCH - 가격 수정
        print()
        print("=" * 50)
        print(f"[STEP 2] 가격 수정: Price={new_price}, CostPrice={new_cost}")
        patch_data = {
            "data": [
                {
                    "MasterCode": master_code,
                    "Price": str(new_price),
                    "CostPrice": str(new_cost),
                }
            ]
        }
        print(f"  Request body: {json.dumps(patch_data)}")

        resp2 = await client.patch(
            f"{EMP_BASE_URL}/prods",
            headers=headers,
            json=patch_data,
        )
        print(f"  Status: {resp2.status_code}")
        result = resp2.json()
        print(f"  Response: {json.dumps(result, ensure_ascii=False)}")

        # Step 3: 검증 - 다시 조회
        print()
        print("=" * 50)
        print("[STEP 3] 수정 후 검증 조회")
        await asyncio.sleep(2)  # 반영 대기
        resp3 = await client.get(
            f"{EMP_BASE_URL}/prods",
            headers=headers,
            params={"MasterCode": master_code},
        )
        print(f"Status: {resp3.status_code}")
        data3 = resp3.json()
        if isinstance(data3, list) and data3:
            prod3 = data3[0] if isinstance(data3[0], dict) else data3
        elif isinstance(data3, dict):
            prod3 = data3
        else:
            prod3 = data3

        if isinstance(prod3, dict):
            print(f"  Price (판매가): {prod3.get('Price', 'N/A')}")
            print(f"  CostPrice (원가): {prod3.get('CostPrice', 'N/A')}")
            print(f"  StreetPrice (시중가): {prod3.get('StreetPrice', 'N/A')}")

            # 검증
            actual_price = str(prod3.get("Price", ""))
            if actual_price == str(new_price):
                print(f"\n  >>> SUCCESS: 가격이 {new_price}으로 정상 변경됨!")
            else:
                print(
                    f"\n  >>> FAIL: 가격이 변경되지 않음! 현재={actual_price}, 기대={new_price}"
                )
        else:
            print(f"  Raw: {json.dumps(data3, ensure_ascii=False)[:200]}")


asyncio.run(main())
