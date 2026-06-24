"""lottehome_credentials samba_settings + lottehome 계정 password 제거."""
import asyncio, json, asyncpg
from backend.core.config import settings

REMOVE_KEYS = ['password', 'agncNo']  # agncNo는 글로벌 key에서만 잘못된 값(037800LT) 보유

async def main():
    c = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port, ssl=False,
        database=settings.write_db_name, user=settings.write_db_user,
        password=settings.write_db_password
    )

    # 1. lottehome_credentials (글로벌) — password + agncNo 제거
    row = await c.fetchrow("SELECT value FROM samba_settings WHERE key='lottehome_credentials' AND tenant_id IS NULL")
    if row:
        val = json.loads(row['value']) if isinstance(row['value'], str) else dict(row['value'])
        print("글로벌 lottehome_credentials:", {k: v for k, v in val.items() if k in REMOVE_KEYS})
        for k in REMOVE_KEYS:
            val.pop(k, None)
        await c.execute(
            "UPDATE samba_settings SET value=$1::json WHERE key='lottehome_credentials' AND tenant_id IS NULL",
            json.dumps(val)
        )
        print("  → 제거 완료")

    # 2. tn_...:lottehome_credentials — password만 제거 (agncNo는 정상값 "01032087310")
    row2 = await c.fetchrow("SELECT key, value FROM samba_settings WHERE key LIKE '%:lottehome_credentials'")
    if row2:
        val2 = json.loads(row2['value']) if isinstance(row2['value'], str) else dict(row2['value'])
        print(f"테넌트 {row2['key']}: password={val2.get('password')!r}")
        val2.pop('password', None)
        await c.execute(
            "UPDATE samba_settings SET value=$1::json WHERE key=$2",
            json.dumps(val2), row2['key']
        )
        print("  → password 제거 완료")

    # 3. lottehome 계정 additional_fields.password 제거
    accs = await c.fetch("SELECT id, account_label FROM samba_market_account WHERE market_type='lottehome' AND additional_fields->>'password' IS NOT NULL")
    for a in accs:
        print(f"계정 {a['account_label']}: password 제거")
        await c.execute(
            "UPDATE samba_market_account SET additional_fields=(additional_fields::jsonb - 'password')::json, updated_at=now() WHERE id=$1",
            a['id']
        )

    await c.close()
    print("\n완료.")

asyncio.run(main())
