"""고경 스마트스토어 마스마룰즈 잔존 상품 식별·삭제.

브랜드명이 검색 응답에 안 나오므로, 각 originProductNo를 GET하여 name으로 필터.
"""

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
    print(f"[{acc.account_label}] origin 번호 수집 시작")

    # 1) 모든 SALE+OUTOFSTOCK+SUSPENSION+CLOSE+WAIT origin 번호 수집
    all_origins: list[str] = []
    page = 1
    total = 0
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
        total = res.get("totalElements", 0)
        for it in contents:
            on = it.get("originProductNo")
            if on:
                all_origins.append(str(on))
        if page == 1 or page % 20 == 0:
            print(f"  page {page}: 누적 origin {len(all_origins)} / 전체 {total}")
        if len(all_origins) >= total:
            break
        page += 1

    print(f"\n[고경] 전체 origin 수: {len(all_origins)}건")

    # 2) 각 origin GET → name에 마스마룰즈 매칭
    masma_origins: list[str] = []
    print("origin GET 진행 중 (name 매칭)...")
    for i, on in enumerate(all_origins, 1):
        try:
            r = await client.get_product(on)
            origin = r.get("originProduct") or {}
            name = origin.get("name") or ""
            if "마스마룰즈" in name or "MASMARULEZ" in name.upper():
                masma_origins.append(on)
        except Exception:
            pass
        if i % 100 == 0:
            print(f"  {i}/{len(all_origins)}: 마스마룰즈 누적 {len(masma_origins)}")
        await asyncio.sleep(0.05)

    print(f"\n[고경] 마스마룰즈 origin {len(masma_origins)}개 식별")
    if not masma_origins:
        print("삭제 대상 없음 — 스킵")
        return

    # 3) 일괄 삭제
    ok = 0
    fail = 0
    for i, on in enumerate(masma_origins, 1):
        try:
            r = await client.delete_product(on)
            if r.get("already_deleted"):
                fail += 1
            else:
                ok += 1
            if i % 5 == 0 or i == len(masma_origins):
                print(f"  [{i}/{len(masma_origins)}] OK={ok}, FAIL={fail}")
        except Exception as e:
            fail += 1
            print(
                f"  [{i}/{len(masma_origins)}] {on} 실패: {type(e).__name__}: {str(e)[:80]}"
            )
        await asyncio.sleep(0.4)

    print(f"\n[고경 마켓삭제 완료] 성공 {ok} / 실패 {fail}")


if __name__ == "__main__":
    asyncio.run(main())
