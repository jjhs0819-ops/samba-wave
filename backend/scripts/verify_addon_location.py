"""스마트스토어 productAddItems 정확한 위치 검증 — 기존 등록된 1377156 origin을 PUT으로 추가옵션 주입."""

import asyncio
import json
from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.smartstore import SmartStoreClient


GADI = "ma_01KM2K57Z8BQY984WC4HE93VQJ"
ORIGIN_NO = "13453384641"  # 방금 등록한 1377156


def addon_payload() -> list[dict]:
    return [
        {
            "groupName": "Shoulder strap 추가",
            "items": [
                {
                    "itemName": "Cotton beige",
                    "price": 10000,
                    "stockQuantity": 99,
                    "usable": True,
                },
                {
                    "itemName": "Cotton black",
                    "price": 10000,
                    "stockQuantity": 99,
                    "usable": True,
                },
                {
                    "itemName": "White",
                    "price": 10000,
                    "stockQuantity": 99,
                    "usable": True,
                },
            ],
        }
    ]


async def main() -> None:
    async with get_read_session() as session:
        acc = await session.get(SambaMarketAccount, GADI)
    extras = getattr(acc, "additional_fields", None) or {}
    client = SmartStoreClient(extras.get("clientId"), extras.get("clientSecret"))

    # 1) GET — 현재 페이로드 가져오기
    print("[GET] 현재 상품 조회 ...")
    r = await client.get_product(ORIGIN_NO)
    origin = r.get("originProduct") or {}
    # readonly 필드 제거
    for k in [
        "productNo",
        "channelProducts",
        "regDate",
        "modifiedDate",
        "saleStartDate",
        "saleEndDate",
    ]:
        origin.pop(k, None)

    # 2-A) Variant A: productAddItems 를 originProduct TOP-level 에 추가
    payload_A = {"originProduct": {**origin, "productAddItems": addon_payload()}}
    if "smartstoreChannelProduct" in r:
        payload_A["smartstoreChannelProduct"] = r["smartstoreChannelProduct"]
    print("\n[Variant A: originProduct.productAddItems] PUT 시도")
    try:
        await client.update_product(ORIGIN_NO, payload_A)
        print("  ✅ PUT 200")
    except Exception as e:
        print(f"  ❌ PUT 실패: {str(e)[:200]}")

    # 3) GET 으로 재확인
    print("\n[GET 재확인]")
    r2 = await client.get_product(ORIGIN_NO)
    o2 = r2.get("originProduct") or {}
    print(f"  originProduct 키: {list(o2.keys())}")
    if "productAddItems" in o2:
        print(
            f"  ✅ productAddItems @ originProduct: {json.dumps(o2['productAddItems'], ensure_ascii=False)[:400]}"
        )
    else:
        # detailAttribute 확인
        da = o2.get("detailAttribute") or {}
        if "productAddItems" in da:
            print(
                f"  ✅ productAddItems @ detailAttribute: {json.dumps(da['productAddItems'], ensure_ascii=False)[:400]}"
            )
        else:
            print("  ❌ productAddItems 키 응답에 없음 — 위치/스키마 모두 잘못")
    # 전체 응답 다른 키들 인쇄 — 우리가 모르는 위치에 들어갔을 수도
    print(
        f"\n  smartstoreChannelProduct 키: {list((r2.get('smartstoreChannelProduct') or {}).keys())}"
    )
    full = json.dumps(r2, ensure_ascii=False)
    idx = full.find("addItem")
    while idx != -1:
        print(f"  ... addItem @ idx={idx}: '{full[max(0, idx - 30) : idx + 150]}'")
        idx = full.find("addItem", idx + 5)


if __name__ == "__main__":
    asyncio.run(main())
