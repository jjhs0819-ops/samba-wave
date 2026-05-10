"""고경 스마트스토어 전체 상품(43건, 모두 마스마룰즈) 일괄 삭제."""

import asyncio
from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.smartstore import SmartStoreClient


GOGYUNG_ID = "ma_01KM04SY2TABXPNTTJFCVTX550"


async def main() -> None:
    async with get_read_session() as session:
        acc = await session.get(SambaMarketAccount, GOGYUNG_ID)
        extras = getattr(acc, "additional_fields", None) or {}
        cid = extras.get("clientId", "") or getattr(acc, "api_key", "") or ""
        csec = extras.get("clientSecret", "") or getattr(acc, "api_secret", "") or ""

    client = SmartStoreClient(cid, csec)

    # 1) origin 번호 모두 수집
    all_origins: list[str] = []
    page = 1
    while page <= 10:
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
            if on:
                all_origins.append(str(on))
        if len(all_origins) >= res.get("totalElements", 0):
            break
        page += 1

    print(f"[고경] 전체 origin: {len(all_origins)}건")
    if not all_origins:
        return

    # 안전 가드 — 50건 초과면 중단 (예상 43건 대비 큰 폭 차이는 의심)
    if len(all_origins) > 60:
        print(f"⚠️ {len(all_origins)}건은 예상(43)보다 많음 — 삭제 중단")
        return

    # 2) 각 origin GET → name 확인 후 마스마룰즈만 필터
    masma_origins: list[str] = []
    other_origins: list[tuple[str, str]] = []
    for i, on in enumerate(all_origins, 1):
        try:
            r = await client.get_product(on)
            origin = r.get("originProduct") or {}
            name = origin.get("name") or ""
            if "마스마룰즈" in name:
                masma_origins.append(on)
            else:
                other_origins.append((on, name[:40]))
        except Exception as e:
            print(f"  GET {on} 실패: {type(e).__name__}: {str(e)[:60]}")
        await asyncio.sleep(0.5)

    print(
        f"\n[고경] 마스마룰즈 매칭 {len(masma_origins)}건, 기타 {len(other_origins)}건"
    )
    for on, n in other_origins[:5]:
        print(f"  기타 샘플: {on} -- {n}")

    if not masma_origins:
        print("삭제 대상 없음")
        return

    # 3) 일괄 삭제
    ok = 0
    fail = 0
    for i, on in enumerate(masma_origins, 1):
        try:
            r = await client.delete_product(on)
            if r.get("already_deleted"):
                fail += 1
                print(f"  [{i}/{len(masma_origins)}] {on}: 이미 삭제")
            else:
                ok += 1
        except Exception as e:
            fail += 1
            print(
                f"  [{i}/{len(masma_origins)}] {on} 실패: {type(e).__name__}: {str(e)[:60]}"
            )
        await asyncio.sleep(0.4)

    print(f"\n[고경 마스마룰즈 마켓삭제 완료] 성공 {ok} / 실패 {fail}")


if __name__ == "__main__":
    asyncio.run(main())
