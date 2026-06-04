"""#348 진단: 롯데홈쇼핑 조회 API 0005 에러 raw 응답 덤프 (READ-ONLY).

배송비정책/반품지/MD상품군 조회를 현재 파라미터로 호출하고 raw XML 전문을 출력.
0005 에러 응답에 누락 파라미터명/힌트가 있는지 확인용. 아무것도 변경 안 함.
"""

import asyncio

from sqlalchemy import text

from backend.db.orm import get_write_session
from backend.domain.samba.proxy.lottehome import LotteHomeClient


async def _make_client(session):
    row = (
        await session.execute(
            text(
                "SELECT seller_id, api_key, additional_fields "
                "FROM samba_market_account "
                "WHERE market_type='lottehome' AND is_active=true LIMIT 1"
            )
        )
    ).first()
    if not row:
        print("lottehome 활성 계정 없음")
        return None
    extras = row.additional_fields or {}
    user_id = extras.get("userId") or row.seller_id or ""
    return LotteHomeClient(
        user_id,
        extras.get("password", ""),
        extras.get("agncNo", ""),
        extras.get("env", "prod"),
    )


async def _dump(client, name, api, params):
    cert = await client._ensure_auth()
    p = {"subscriptionId": cert, **params}
    print(f"\n===== {name} ({api}) params={list(p.keys())} =====")
    try:
        res = await client._call_api_auto_retry(api, "GET", p)
        raw = res.get("rawXml", "") if isinstance(res, dict) else str(res)
        print(raw[:1500])
    except Exception as e:
        print(f"EXCEPTION: {type(e).__name__}: {str(e)[:500]}")


async def main() -> None:
    async with get_write_session() as session:
        client = await _make_client(session)
        if not client:
            return
        await _dump(client, "배송비정책", "searchDlvPolcInfoListOpenApi.lotte", {})
        await _dump(
            client, "반품지", "searchReturnListOpenApi.lotte", {"dlvp_tp_cd": "10"}
        )
        await _dump(client, "MD상품군", "searchMDListOpenApi.lotte", {})
        await session.rollback()


if __name__ == "__main__":
    asyncio.run(main())
