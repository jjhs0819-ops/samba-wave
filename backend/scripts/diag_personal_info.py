"""store_* samba_settings + 계정 additional_fields에서 개인정보 패턴 탐지·제거."""
import asyncio, json, asyncpg
from backend.core.config import settings

PATTERNS = ['037800LT', 'gemini0674', 'gemini0674@@']

async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port, ssl=False,
        database=settings.write_db_name, user=settings.write_db_user,
        password=settings.write_db_password
    )

    # 1. samba_settings store_* 확인
    print("=== samba_settings store_* ===")
    rows = await conn.fetch(
        "SELECT key, value FROM samba_settings WHERE key LIKE 'store_%'"
    )
    for r in rows:
        try:
            val = json.loads(r['value']) if isinstance(r['value'], str) else r['value']
        except Exception:
            val = r['value']
        if isinstance(val, dict):
            hits = {k: v for k, v in val.items() if any(p in str(v) for p in PATTERNS)}
            if hits:
                print(f"  KEY={r['key']} 오염 필드: {hits}")
    print()

    # 2. samba_market_account additional_fields 확인
    print("=== samba_market_account ===")
    accs = await conn.fetch(
        "SELECT id, market_type, account_label, additional_fields FROM samba_market_account"
    )
    dirty_accounts: list[tuple] = []  # (id, market_type, dirty_keys)
    for a in accs:
        try:
            af = json.loads(a['additional_fields']) if isinstance(a['additional_fields'], str) else a['additional_fields']
        except Exception:
            af = {}
        if isinstance(af, dict):
            hits = {k: v for k, v in af.items() if any(p in str(v) for p in PATTERNS)}
            if hits:
                print(f"  {a['market_type']}/{a['account_label']}: {hits}")
                dirty_accounts.append((a['id'], a['market_type'], list(hits.keys())))

    print()
    print(f"오염 계정 {len(dirty_accounts)}개 — additional_fields 키 제거 시작")

    # 3. additional_fields에서 오염 키 제거
    for acc_id, mtype, dirty_keys in dirty_accounts:
        remove_expr = 'additional_fields::jsonb'
        for k in dirty_keys:
            remove_expr = f"({remove_expr} - '{k}')"
        await conn.execute(
            f"UPDATE samba_market_account SET additional_fields = ({remove_expr})::json, updated_at = now() WHERE id = $1",
            acc_id
        )
        print(f"  제거: {mtype}/{acc_id} 키={dirty_keys}")

    # 4. samba_settings store_* 오염 키 제거
    print()
    print("=== samba_settings 오염 키 제거 ===")
    for r in rows:
        try:
            val = json.loads(r['value']) if isinstance(r['value'], str) else r['value']
        except Exception:
            continue
        if isinstance(val, dict):
            dirty_keys = [k for k, v in val.items() if any(p in str(v) for p in PATTERNS)]
            if dirty_keys:
                cleaned = {k: v for k, v in val.items() if k not in dirty_keys}
                await conn.execute(
                    "UPDATE samba_settings SET value = $1::json WHERE key = $2",
                    json.dumps(cleaned), r['key']
                )
                print(f"  {r['key']} 제거 키={dirty_keys}")

    await conn.close()
    print("\n완료.")

asyncio.run(main())
