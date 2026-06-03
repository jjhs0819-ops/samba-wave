"""롯데홈쇼핑 실제 노출가 직접 조회 (search_goods_view)."""

import asyncio
import json
import sys

GOODS_NOS = sys.argv[1:] or ["LE1221138195"]


async def main() -> None:
    from sqlalchemy import text
    from backend.db.orm import get_read_sessionmaker
    from backend.domain.samba.proxy.lottehome import LotteHomeClient

    RS = get_read_sessionmaker()
    async with RS() as s:
        a = (
            (
                await s.execute(
                    text(
                        "SELECT id, seller_id, additional_fields, tenant_id "
                        "FROM samba_market_account WHERE market_type='lottehome' LIMIT 1"
                    )
                )
            )
            .mappings()
            .first()
        )
        ext = a["additional_fields"] or {}
        if isinstance(ext, str):
            ext = json.loads(ext)
        from backend.domain.samba.account.resolver import resolve_market_creds

        store = await resolve_market_creds(
            s, a["tenant_id"], market_type="lottehome", store_key="store_lottehome"
        )
        store = store if isinstance(store, dict) else {}

    def pick(*keys):
        for src in (ext, store):
            for k in keys:
                v = src.get(k, "")
                if v:
                    return str(v)
        return ""

    user_id = pick("userId") or (a["seller_id"] or "")
    password = pick("password")
    agnc_no = pick("agncNo")
    env = pick("env") or "prod"
    print(
        f"user_id={user_id} agnc_no={agnc_no} env={env} pw={'O' if password else 'X'}"
    )

    client = LotteHomeClient(user_id, password, agnc_no, env)
    for gn in GOODS_NOS:
        try:
            res = await client.search_goods_view(gn)
            print(f"\n=== {gn} ===")
            txt = json.dumps(res, ensure_ascii=False, default=str)
            # 가격 관련 키만 추려 출력
            print(txt[:1500])
        except Exception as e:
            print(f"{gn} 조회 실패: {repr(e)}")


if __name__ == "__main__":
    asyncio.run(main())
