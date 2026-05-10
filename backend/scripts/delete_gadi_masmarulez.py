"""가디 스마트스토어 계정의 마스마룰즈 상품 식별·일괄 삭제."""

import asyncio
from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.smartstore import SmartStoreClient


GADI_ID = "ma_01KM04SY2TABXPNTTJFCVTX550"  # 고경


async def main() -> None:
    async with get_read_session() as session:
        acc = await session.get(SambaMarketAccount, GADI_ID)
        if not acc:
            print("계정 없음")
            return
        extras = getattr(acc, "additional_fields", None) or {}
        cid = extras.get("clientId", "") or getattr(acc, "api_key", "") or ""
        csec = extras.get("clientSecret", "") or getattr(acc, "api_secret", "") or ""

    client = SmartStoreClient(cid, csec)
    print(f"[{acc.account_label}] 마스마룰즈 식별 시작")

    # 페이지로 전체 SALE 상품 조회 → 이름 필터
    masma_origins: list[str] = []
    brand_counter: dict[str, int] = {}
    page = 1
    while page <= 200:
        body = {
            "productStatusTypes": ["SALE", "OUTOFSTOCK", "SUSPENSION", "CLOSE", "WAIT"],
            "page": page,
            "size": 100,
            "orderType": "NO",
        }
        res = await client._call_api("POST", "/v1/products/search", body=body)
        contents = res.get("contents", [])
        if not contents:
            break
        for it in contents:
            on = it.get("originProductNo")
            brand = it.get("brandName") or "(empty)"
            brand_counter[brand] = brand_counter.get(brand, 0) + 1
            model = it.get("modelName") or ""
            cat = it.get("wholeCategoryName") or ""
            blob = f"{brand} {model} {cat}".upper()
            if on and (
                "마스마룰즈" in brand or "MASMARULEZ" in blob or "마스마룰즈" in model
            ):
                masma_origins.append(str(on))
        total = res.get("totalElements", 0)
        print(
            f"  page {page}: 누적 {len(masma_origins)}개 (전체 {total}건 중 {page * 100}건 스캔)"
        )
        if page * 100 >= total:
            break
        page += 1

    # 브랜드 분포 (top 20)
    print("\n[가디] 브랜드 분포 (top 20):")
    for b, c in sorted(brand_counter.items(), key=lambda x: -x[1])[:20]:
        print(f"  {b}: {c}건")

    print(f"\n[가디] 마스마룰즈 origin 상품 {len(masma_origins)}개 식별")
    if not masma_origins:
        print("삭제 대상 없음")
        return

    # 일괄 삭제
    ok = 0
    fail = 0
    for i, on in enumerate(masma_origins, 1):
        try:
            r = await client.delete_product(on)
            if r.get("already_deleted"):
                fail += 1
                print(f"  [{i}/{len(masma_origins)}] {on}: 이미 삭제 (404)")
            else:
                ok += 1
                if i % 10 == 0:
                    print(f"  [{i}/{len(masma_origins)}] 누적 OK={ok}, FAIL={fail}")
        except Exception as e:
            fail += 1
            print(
                f"  [{i}/{len(masma_origins)}] {on} 삭제 실패: {type(e).__name__}: {str(e)[:80]}"
            )
        await asyncio.sleep(0.4)

    print(f"\n[가디 마켓삭제 완료] 성공 {ok}건 / 실패 {fail}건")


if __name__ == "__main__":
    asyncio.run(main())
