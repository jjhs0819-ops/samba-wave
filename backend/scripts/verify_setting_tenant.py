"""save_setting tenant_id 채움 검증 — 프로덕션 DB 직접 실행.

CLAUDE.md 8번 "raw SQL 함정" 규칙: upsert 수정 시 푸시 전 직접 검증 필수.
검증 케이스:
  1) HTTP 컨텍스트 신규 저장 → tenant_id = tid 로 stamp
  2) worker 컨텍스트(tid=None) 재저장 → 기존 tenant_id 보존(안 지워짐)
  3) tenant_id NULL 기존 row → HTTP 재저장 시 tid 로 자가 교정
검증 후 테스트 키 삭제(기존 운영 키 무영향).
"""

import asyncio

from backend.core.tenant_context import current_tenant_id
from backend.db.orm import get_write_session
from backend.domain.samba.forbidden.repository import (
    SambaForbiddenWordRepository,
    SambaSettingsRepository,
)
from backend.domain.samba.forbidden.service import SambaForbiddenService
from sqlalchemy import text

TEST_TID = "tn_verify_test_0001"
TEST_KEY_NEW = "__verify_tenant_new__"
TEST_KEY_NULL = "__verify_tenant_null__"


async def _read_tid(session, key):
    row = await session.execute(
        text("SELECT tenant_id FROM samba_settings WHERE key = :k"), {"k": key}
    )
    r = row.first()
    return r[0] if r else "<없음>"


async def main():
    async with get_write_session() as session:
        svc = SambaForbiddenService(
            SambaForbiddenWordRepository(session),
            SambaSettingsRepository(session),
        )

        # 정리(이전 잔여 테스트 키)
        await session.execute(
            text("DELETE FROM samba_settings WHERE key IN (:a, :b)"),
            {"a": TEST_KEY_NEW, "b": TEST_KEY_NULL},
        )
        await session.commit()

        # --- 케이스 1: HTTP 컨텍스트 신규 저장 → tid stamp
        token = current_tenant_id.set(TEST_TID)
        try:
            await svc.save_setting(TEST_KEY_NEW, {"v": 1})
        finally:
            current_tenant_id.reset(token)
        t1 = await _read_tid(session, TEST_KEY_NEW)
        ok1 = t1 == TEST_TID
        print(
            f"[1] HTTP 신규 저장 tenant_id={t1!r} 기대={TEST_TID!r} → {'OK' if ok1 else 'FAIL'}"
        )

        # --- 케이스 2: worker 컨텍스트(tid=None) 재저장 → 기존 tid 보존
        # current_tenant_id 기본 None
        await svc.save_setting(TEST_KEY_NEW, {"v": 2})
        t2 = await _read_tid(session, TEST_KEY_NEW)
        ok2 = t2 == TEST_TID
        print(
            f"[2] worker 재저장 tenant_id={t2!r} 보존기대={TEST_TID!r} → {'OK' if ok2 else 'FAIL'}"
        )

        # --- 케이스 3: tenant_id NULL 기존 row → HTTP 재저장 자가교정
        await session.execute(
            text(
                "INSERT INTO samba_settings(key, value, tenant_id, updated_at) "
                "VALUES (:k, '{}'::json, NULL, now())"
            ),
            {"k": TEST_KEY_NULL},
        )
        await session.commit()
        t3a = await _read_tid(session, TEST_KEY_NULL)
        token = current_tenant_id.set(TEST_TID)
        try:
            await svc.save_setting(TEST_KEY_NULL, {"v": 3})
        finally:
            current_tenant_id.reset(token)
        t3b = await _read_tid(session, TEST_KEY_NULL)
        ok3 = t3a is None and t3b == TEST_TID
        print(
            f"[3] NULL→HTTP 자가교정 before={t3a!r} after={t3b!r} 기대 None→{TEST_TID!r} "
            f"→ {'OK' if ok3 else 'FAIL'}"
        )

        # 정리
        await session.execute(
            text("DELETE FROM samba_settings WHERE key IN (:a, :b)"),
            {"a": TEST_KEY_NEW, "b": TEST_KEY_NULL},
        )
        await session.commit()

        all_ok = ok1 and ok2 and ok3
        print(f"\n결과: {'전부 OK' if all_ok else '실패 있음 — 푸시 금지'}")


if __name__ == "__main__":
    asyncio.run(main())
