"""samba_settings tenant_id NULL 백필 — 단일 테넌트 환경 전용.

이슈 #510: backfill(2026-05-18) 이후 save_setting 으로 저장된 키가 tenant_id=NULL.
가드: 비-NULL tenant_id 가 정확히 1개일 때만 실행(다중 테넌트면 오배정 위험 → 중단).
prefixed 키('{tid}:...')는 prefix 의 tid 로, bare 키는 단일 테넌트 tid 로 채움.
"""

import asyncio

from backend.db.orm import get_write_session
from sqlalchemy import text


async def main():
    async with get_write_session() as session:
        # 비-NULL tenant 후보
        rows = (
            await session.execute(
                text(
                    "SELECT DISTINCT tenant_id FROM samba_settings "
                    "WHERE tenant_id IS NOT NULL"
                )
            )
        ).all()
        tenants = [r[0] for r in rows]
        print(f"비-NULL tenant: {tenants}")
        if len(tenants) != 1:
            print(f"테넌트 {len(tenants)}개 — 단일 아님. 백필 중단(오배정 방지).")
            return
        tid = tenants[0]

        # 현재 NULL 키 목록
        null_rows = (
            await session.execute(
                text(
                    "SELECT key FROM samba_settings WHERE tenant_id IS NULL ORDER BY key"
                )
            )
        ).all()
        null_keys = [r[0] for r in null_rows]
        print(f"NULL 키 {len(null_keys)}개:")
        for k in null_keys:
            print(f"  - {k}")

        if not null_keys:
            print("백필 대상 없음.")
            return

        # 백필: prefixed 키는 prefix 의 tid 우선, 아니면 단일 tid
        updated = 0
        for k in null_keys:
            target = tid
            if ":" in k:
                pref = k.split(":", 1)[0]
                if pref.startswith("tn_"):
                    target = pref
            await session.execute(
                text(
                    "UPDATE samba_settings SET tenant_id = :tid "
                    "WHERE key = :k AND tenant_id IS NULL"
                ),
                {"tid": target, "k": k},
            )
            updated += 1
            print(f"  ✓ {k} → {target}")
        await session.commit()

        remain = (
            await session.execute(
                text("SELECT count(*) FROM samba_settings WHERE tenant_id IS NULL")
            )
        ).scalar()
        print(f"\n백필 완료: {updated}개 / 남은 NULL: {remain}")


if __name__ == "__main__":
    asyncio.run(main())
