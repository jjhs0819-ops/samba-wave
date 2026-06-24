"""GS샵 market account 조회."""
import asyncio, json, sys
sys.path.insert(0, "/app/backend")

import asyncpg
from backend.core.config import settings as cfg


async def main():
    conn = await asyncpg.connect(
        host=cfg.write_db_host, port=cfg.write_db_port,
        database=cfg.write_db_name, user=cfg.write_db_user,
        password=cfg.write_db_password, ssl=False,
    )

    # samba_market_account 구조 확인
    cols = await conn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='samba_market_account' ORDER BY ordinal_position"
    )
    print("=== samba_market_account 컬럼 ===")
    for c in cols:
        print(f"  {c['column_name']}")

    # GS샵 계정 조회
    rows = await conn.fetch(
        "SELECT * FROM samba_market_account WHERE market_type ILIKE '%gs%' LIMIT 10"
    )
    print(f"\n=== GS샵 계정: {len(rows)}개 ===")
    for r in rows:
        d = dict(r)
        # additional_fields JSON 파싱
        af = d.get("additional_fields")
        if isinstance(af, str):
            af = json.loads(af) if af else {}
        print(f"  id={d.get('id')} market_type={d.get('market_type')} seller_id={d.get('seller_id')}")
        print(f"  additional_fields={json.dumps(af or {}, ensure_ascii=False)[:400]}")

    await conn.close()


asyncio.run(main())
