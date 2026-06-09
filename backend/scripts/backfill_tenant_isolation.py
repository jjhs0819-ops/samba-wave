"""테넌트 격리 컬럼 backfill — 기존 행을 올바른 테넌트로 재귀속.

마이그레이션(zzzzz_add_tenant_isolation_cols)으로 tenant_id 컬럼을 추가한 뒤,
이미 쌓인 기존 행들을 소유 테넌트로 귀속한다.

매핑 규칙:
- samba_cs_inquiry: account_id → samba_market_account.id (정확), 없으면
  account_name → samba_market_account.account_label (단일 테넌트 매칭만)
- samba_login_history: user_id → samba_user.tenant_id

미매칭 행(account_name NULL/라벨 미존재/복수 테넌트 충돌)은 건수만 보고하고
임의로 본부에 박지 않는다(또 다른 오염 방지).

실행:
  dry-run(기본): SELECT 카운트만        python backfill_tenant_isolation.py
  실제 적용:                            python backfill_tenant_isolation.py --apply
"""

import asyncio
import sys

import asyncpg

from backend.core.config import settings


async def main(apply: bool) -> None:
    conn = await asyncpg.connect(
        user=settings.write_db_user,
        password=settings.write_db_password,
        host=settings.write_db_host,
        port=settings.write_db_port,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        # 컬럼 존재 가드 (마이그레이션 선행 필수)
        for tbl in ("samba_cs_inquiry", "samba_login_history"):
            has = await conn.fetchval(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name=$1 AND column_name='tenant_id'",
                tbl,
            )
            if not has:
                print(f"[중단] {tbl}.tenant_id 컬럼 없음 — 마이그레이션 먼저 적용 필요")
                return

        print(f"=== backfill ({'APPLY' if apply else 'DRY-RUN'}) ===\n")

        # ── 1) CS: account_id → market_account.id ──
        cs_by_id = (
            "UPDATE samba_cs_inquiry c SET tenant_id = m.tenant_id "
            "FROM samba_market_account m "
            "WHERE c.account_id = m.id "
            "AND c.tenant_id IS NULL AND m.tenant_id IS NOT NULL"
        )
        # ── 2) CS: account_name → account_label (단일 테넌트 라벨만) ──
        cs_by_name = (
            "UPDATE samba_cs_inquiry c SET tenant_id = sub.tid "
            "FROM (SELECT account_label, MIN(tenant_id) AS tid "
            "      FROM samba_market_account WHERE tenant_id IS NOT NULL "
            "      GROUP BY account_label HAVING COUNT(DISTINCT tenant_id) = 1) sub "
            "WHERE c.account_name = sub.account_label AND c.tenant_id IS NULL"
        )
        # ── 2b) CS: 플레이오토 account_name은 ' (GS이숍)' 같은 마켓 접미가 붙어
        #        account_label과 정확히 안 맞는다. 접미 제거 후 prefix 매칭(단일 테넌트만). ──
        cs_by_name_prefix = (
            "UPDATE samba_cs_inquiry c SET tenant_id = sub.tid "
            "FROM (SELECT account_label, MIN(tenant_id) AS tid "
            "      FROM samba_market_account WHERE tenant_id IS NOT NULL "
            "      GROUP BY account_label HAVING COUNT(DISTINCT tenant_id) = 1) sub "
            "WHERE c.tenant_id IS NULL "
            "AND split_part(c.account_name, ' (', 1) = sub.account_label"
        )
        # ── 3) 로그인이력: user_id → samba_user.tenant_id ──
        lh_by_user = (
            "UPDATE samba_login_history l SET tenant_id = u.tenant_id "
            "FROM samba_user u "
            "WHERE l.user_id = u.id "
            "AND l.tenant_id IS NULL AND u.tenant_id IS NOT NULL"
        )

        if apply:
            r1 = await conn.execute(cs_by_id)
            r2 = await conn.execute(cs_by_name)
            r2b = await conn.execute(cs_by_name_prefix)
            r3 = await conn.execute(lh_by_user)
            print(f"CS  account_id 매칭 귀속: {r1}")
            print(f"CS  account_name 매칭 귀속: {r2}")
            print(f"CS  account_name prefix 매칭 귀속: {r2b}")
            print(f"로그인이력 user_id 매칭 귀속: {r3}")
        else:
            c1 = await conn.fetchval(
                "SELECT count(*) FROM samba_cs_inquiry c "
                "JOIN samba_market_account m ON c.account_id = m.id "
                "WHERE c.tenant_id IS NULL AND m.tenant_id IS NOT NULL"
            )
            c2 = await conn.fetchval(
                "SELECT count(*) FROM samba_cs_inquiry c "
                "JOIN (SELECT account_label, MIN(tenant_id) tid "
                "      FROM samba_market_account WHERE tenant_id IS NOT NULL "
                "      GROUP BY account_label HAVING COUNT(DISTINCT tenant_id)=1) sub "
                "ON c.account_name = sub.account_label "
                "WHERE c.tenant_id IS NULL"
            )
            c3 = await conn.fetchval(
                "SELECT count(*) FROM samba_login_history l "
                "JOIN samba_user u ON l.user_id = u.id "
                "WHERE l.tenant_id IS NULL AND u.tenant_id IS NOT NULL"
            )
            print(f"CS  account_id 매칭 가능: {c1}건")
            print(f"CS  account_name 매칭 가능(중복 제외): {c2}건")
            print(f"로그인이력 user_id 매칭 가능: {c3}건")

        # ── 미매칭 잔여 보고 ──
        cs_left = await conn.fetchval(
            "SELECT count(*) FROM samba_cs_inquiry WHERE tenant_id IS NULL"
        )
        lh_left = await conn.fetchval(
            "SELECT count(*) FROM samba_login_history WHERE tenant_id IS NULL"
        )
        cs_total = await conn.fetchval("SELECT count(*) FROM samba_cs_inquiry")
        lh_total = await conn.fetchval("SELECT count(*) FROM samba_login_history")
        print(
            f"\n미귀속 잔여 — CS: {cs_left}/{cs_total}, 로그인이력: {lh_left}/{lh_total}"
        )

        # blueh0810 확인
        bh = await conn.fetch(
            "SELECT id, account_name, tenant_id FROM samba_cs_inquiry "
            "WHERE account_name LIKE '%blueh0810%' OR account_name LIKE '%블루하트%'"
        )
        print("\nblueh0810 CS 귀속 결과:")
        for r in bh:
            print(f"  {r['id']} acct={r['account_name']!r} tenant={r['tenant_id']!r}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
