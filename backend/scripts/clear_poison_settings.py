"""store_poison samba_settings 초기화 스크립트.

잘못 저장된 POIZON 인증정보를 DB에서 지워 폼이 빈 상태로 시작하게 만든다.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import asyncpg
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host=settings.DB_WRITE_HOST,
        port=settings.DB_WRITE_PORT,
        user=settings.DB_WRITE_USER,
        password=settings.DB_WRITE_PASSWORD,
        database=settings.DB_WRITE_NAME,
        ssl=False,
    )
    # store_poison 설정 삭제
    deleted = await conn.execute(
        "DELETE FROM samba_settings WHERE key = 'store_poison' OR key LIKE '%:store_poison'"
    )
    print(f"[DONE] store_poison 삭제: {deleted}")

    # poison market account도 조회 (참고용)
    rows = await conn.fetch(
        "SELECT id, seller_id, account_label, additional_fields FROM samba_market_account WHERE market_type = 'poison'"
    )
    print(f"[INFO] poison market account {len(rows)}개:")
    for r in rows:
        af = dict(r['additional_fields']) if r['additional_fields'] else {}
        print(f"  id={r['id']} seller_id={r['seller_id']} label={r['account_label']} apiKey={af.get('apiKey', '(없음)')}")

    await conn.close()


asyncio.run(main())
