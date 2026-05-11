"""스마트스토어 productAddItems 스키마 직접 실험.

3가지 후보 스키마로 최소 페이로드를 등록 시도 → 응답 + GET 결과 비교해 실제 동작하는 형태 식별.
실험 후 등록된 상품은 즉시 삭제하여 정리.
"""

import asyncio
import json
from sqlalchemy import select
from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.smartstore import SmartStoreClient


CHANOL_ID = "ma_01KM2K57Z8BQY984WC4HE93VQJ"  # 가디 (마스마룰즈 등록 이력 보유)


def base_payload(name_suffix: str, category_id: str = "50003845") -> dict:
    """최소 등록 페이로드 — 색상(2개) 1단 옵션 + 추가옵션."""
    return {
        "originProduct": {
            "statusType": "SALE",
            "saleType": "NEW",
            "leafCategoryId": category_id,
            "name": f"[테스트][addon-probe] 1377156 {name_suffix}",
            "detailContent": "<div>테스트 상품 — 자동 삭제 예정</div>",
            "images": {
                "representativeImage": {
                    "url": "https://image.musinsa.com/images/goods_img/20251001/4710001/4710001_17287313055554_500.jpg"
                }
            },
            "salePrice": 46000,
            "stockQuantity": 99,
            "deliveryInfo": {
                "deliveryType": "DELIVERY",
                "deliveryAttributeType": "NORMAL",
                "deliveryCompany": "CJGLS",
                "deliveryBundleGroupUsable": False,
                "deliveryFee": {
                    "deliveryFeeType": "FREE",
                    "baseFee": 0,
                    "deliveryFeePayType": "PREPAID",
                    "differentialFeeByArea": "NONE",
                },
                "claimDeliveryInfo": {
                    "returnDeliveryCompanyPriorityType": "PRIMARY",
                    "returnDeliveryFee": 3000,
                    "exchangeDeliveryFee": 6000,
                    "shippingAddressId": 0,
                    "returnAddressId": 0,
                },
                "installation": False,
                "installationFee": False,
                "expectedDeliveryPeriodType": "STANDARD",
                "customProductAfterOrderYn": False,
            },
            "detailAttribute": {
                "minorPurchasable": True,
                "afterServiceInfo": {
                    "afterServiceTelephoneNumber": "010-0000-0000",
                    "afterServiceGuideContent": "테스트",
                },
                "originAreaInfo": {"originAreaCode": "0200037"},
                "sellerCodeInfo": {"sellerManagementCode": f"TEST_{name_suffix}"},
                "optionInfo": {
                    "optionCombinationSortType": "CREATE",
                    "optionCombinationGroupNames": {"optionGroupName1": "색상"},
                    "optionCombinations": [
                        {
                            "optionName1": "Cotton beige",
                            "stockQuantity": 99,
                            "price": 0,
                            "usable": True,
                        },
                        {
                            "optionName1": "Cotton black",
                            "stockQuantity": 99,
                            "price": 0,
                            "usable": True,
                        },
                    ],
                    "useStockManagement": True,
                },
            },
        },
        "smartstoreChannelProduct": {
            "channelProductName": f"[테스트][addon-probe] 1377156 {name_suffix}",
            "storeKeepExclusiveProduct": False,
            "naverShoppingRegistration": False,
            "channelProductDisplayStatusType": "ON",
        },
    }


def schema_A_nested() -> list[dict]:
    """후보 A: [{groupName, items: [...]}, ...] — 그룹별 중첩."""
    return [
        {
            "groupName": "Shoulder strap",
            "items": [
                {
                    "itemName": "Strap Beige",
                    "price": 10000,
                    "stockQuantity": 99,
                    "usable": True,
                },
                {
                    "itemName": "Strap Black",
                    "price": 10000,
                    "stockQuantity": 99,
                    "usable": True,
                },
            ],
        }
    ]


def schema_B_flat() -> list[dict]:
    """후보 B: [{groupName, itemName, ...}, ...] — 플랫."""
    return [
        {
            "groupName": "Shoulder strap",
            "itemName": "Strap Beige",
            "price": 10000,
            "stockQuantity": 99,
            "usable": True,
        },
        {
            "groupName": "Shoulder strap",
            "itemName": "Strap Black",
            "price": 10000,
            "stockQuantity": 99,
            "usable": True,
        },
    ]


def schema_C_alt() -> list[dict]:
    """후보 C: itemName 만 (그룹 없이) — Naver 일부 옛 스펙."""
    return [
        {
            "itemName": "Shoulder strap Beige",
            "price": 10000,
            "stockQuantity": 99,
            "usable": True,
        },
        {
            "itemName": "Shoulder strap Black",
            "price": 10000,
            "stockQuantity": 99,
            "usable": True,
        },
    ]


async def try_one(client: SmartStoreClient, suffix: str, productAddItems) -> dict:
    payload = base_payload(suffix)
    payload["originProduct"]["productAddItems"] = productAddItems
    try:
        result = await client._call_api(
            "POST", "/v2/products", body=payload, timeout=90
        )
        # 응답에서 originProductNo / smartstoreChannelProductNo 추출
        origin_no = result.get("originProductNo") or (result.get("data") or {}).get(
            "originProductNo"
        )
        channel_no = result.get("smartstoreChannelProductNo") or (
            result.get("data") or {}
        ).get("smartstoreChannelProductNo")
        print(f"[{suffix}] ✅ POST 성공 origin={origin_no} channel={channel_no}")
        # GET으로 실제 저장된 productAddItems 확인
        if origin_no:
            try:
                got = await client.get_product(str(origin_no))
                p = got.get("originProduct") or {}
                detail = p.get("detailAttribute", {}) or {}
                add_items = detail.get("productAddItems") or []
                print(
                    f"[{suffix}] GET productAddItems 응답: {json.dumps(add_items, ensure_ascii=False)[:400]}"
                )
            except Exception as ge:
                print(f"[{suffix}] GET 실패: {ge}")
            # 즉시 삭제 — 잔존 방지
            try:
                await client.delete_product(str(origin_no))
                print(f"[{suffix}] DELETE OK origin={origin_no}")
            except Exception as de:
                print(f"[{suffix}] DELETE 실패: {de}")
        return {"ok": True, "origin_no": origin_no, "channel_no": channel_no}
    except Exception as e:
        msg = str(e)[:300]
        print(f"[{suffix}] ❌ POST 실패: {msg}")
        return {"ok": False, "error": msg}


async def main() -> None:
    async with get_read_session() as session:
        acc = await session.get(SambaMarketAccount, CHANOL_ID)
        if not acc:
            print("계정 없음")
            return
        extras = getattr(acc, "additional_fields", None) or {}
        cid = extras.get("clientId", "") or getattr(acc, "api_key", "") or ""
        csec = extras.get("clientSecret", "") or getattr(acc, "api_secret", "") or ""

    client = SmartStoreClient(cid, csec)
    print(f"\n=== 스마트스토어 productAddItems 스키마 실험 ({acc.account_label}) ===\n")

    # DB에서 1377156 이미지 가져오기
    from backend.domain.samba.collector.model import SambaCollectedProduct as _CP

    async with get_read_session() as sess:
        row = (
            await sess.execute(
                select(_CP).where(
                    _CP.source_site == "MUSINSA", _CP.site_product_id == "1377156"
                )
            )
        ).scalar_one_or_none()
    if not row or not row.images:
        print("1377156 이미지 없음")
        return
    src_img = row.images[0]
    print(f"[전처리] 1377156 첫 이미지 업로드 중: {src_img[:80]}")
    img_url = await client.upload_image_from_url(src_img)
    if not img_url:
        print("이미지 업로드 실패 — 종료")
        return
    print(f"  CDN URL: {img_url}")

    # base_payload 의 이미지를 업로드된 URL로 교체하는 헬퍼 패치
    global base_payload
    _orig_base = base_payload

    def patched_base(suffix: str, category_id: str = "50001464") -> dict:
        p = _orig_base(suffix, category_id)
        p["originProduct"]["images"] = {"representativeImage": {"url": img_url}}
        return p

    base_payload = patched_base

    print("\n--- 후보 A (nested groupName+items) ---")
    await try_one(client, "A-nested", schema_A_nested())

    print("\n--- 후보 B (flat groupName+itemName) ---")
    await try_one(client, "B-flat", schema_B_flat())

    print("\n--- 후보 C (itemName 만) ---")
    await try_one(client, "C-itemOnly", schema_C_alt())

    print("\n--- 후보 D (productAddItems 없이 minimal) — sanity check ---")
    await try_one(client, "D-no-addon", [])


if __name__ == "__main__":
    asyncio.run(main())
