"""GS샵 credentials 찾기 스크립트."""
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

    # samba_settings 전체 GS샵 관련 키 검색
    rows = await conn.fetch(
        "SELECT key, value FROM samba_settings WHERE key ILIKE '%gs%' OR key ILIKE '%gsshop%'"
    )
    print(f"=== samba_settings GS 관련: {len(rows)}개 ===")
    for r in rows:
        print(f"  key={r['key']}  value={str(r['value'])[:200]}")

    # samba_channel_account 에서 gsshop 계정 검색
    rows2 = await conn.fetch(
        "SELECT id, market_type, seller_id, additional_fields FROM samba_channel_account "
        "WHERE market_type ILIKE '%gs%' OR market_type ILIKE '%gsshop%' LIMIT 10"
    )
    print(f"\n=== channel_account GS 관련: {len(rows2)}개 ===")
    for r in rows2:
        af = r["additional_fields"]
        if isinstance(af, str):
            af = json.loads(af) if af else {}
        print(f"  id={r['id']} market_type={r['market_type']} seller_id={r['seller_id']}")
        print(f"  additional_fields={json.dumps(af, ensure_ascii=False)[:300]}")

    # store_gsshop key
    rows3 = await conn.fetch(
        "SELECT key, value FROM samba_settings WHERE key ILIKE '%store_gsshop%' OR key ILIKE '%store_gs%'"
    )
    print(f"\n=== store_gsshop: {len(rows3)}개 ===")
    for r in rows3:
        print(f"  key={r['key']}  value={str(r['value'])[:300]}")

    await conn.close()


asyncio.run(main())
