"""#462 scalar 전환 raw SQL 프로덕션 검증 (read-only, rollback).

- scalar dedup 결과가 기존 배열전개 결과와 동일한지
- payload 단일원소 불변식(멀티원소 0건) 실측
- scalar account-lock claim 쿼리 문법/실행 정상 여부 (commit 안 함)
"""

import asyncio

from sqlalchemy import text

from backend.db.orm import get_write_session


async def main() -> None:
    async with get_write_session() as s:
        # 1) 멀티원소 불변식 — 이슈 주장(항상 단일원소) 실측
        multi_pid = (
            await s.execute(
                text(
                    "SELECT count(*) FROM samba_jobs WHERE job_type='autotune_transmit' "
                    "AND json_typeof(payload->'product_ids')='array' "
                    "AND json_array_length(payload->'product_ids')>1"
                )
            )
        ).scalar()
        multi_acc = (
            await s.execute(
                text(
                    "SELECT count(*) FROM samba_jobs WHERE job_type='autotune_transmit' "
                    "AND json_typeof(payload->'target_account_ids')='array' "
                    "AND json_array_length(payload->'target_account_ids')>1"
                )
            )
        ).scalar()
        print(f"[1] 멀티원소 product_ids={multi_pid} target_account_ids={multi_acc} (기대 0)")

        # 2) scalar dedup vs 기존 배열 dedup 결과 동일성
        sample = (
            await s.execute(
                text(
                    "SELECT payload->'product_ids'->>0 AS pid, "
                    "payload->'target_account_ids'->>0 AS acc "
                    "FROM samba_jobs WHERE status='pending' AND job_type='autotune_transmit' "
                    "LIMIT 5"
                )
            )
        ).fetchall()
        print(f"[2] 샘플 pending {len(sample)}건")
        for r in sample:
            pid, acc = r.pid, r.acc
            m_new = (
                await s.execute(
                    text(
                        "SELECT count(*) FROM samba_jobs WHERE job_type='autotune_transmit' "
                        "AND status='pending' AND (payload->'product_ids'->>0)=:pid "
                        "AND (payload->'target_account_ids'->>0)=:acc"
                    ).bindparams(pid=pid, acc=acc)
                )
            ).scalar()
            m_old = (
                await s.execute(
                    text(
                        "SELECT count(*) FROM samba_jobs WHERE job_type='autotune_transmit' "
                        "AND status='pending' "
                        "AND EXISTS(SELECT 1 FROM json_array_elements_text(payload->'product_ids') v WHERE v=:pid) "
                        "AND EXISTS(SELECT 1 FROM json_array_elements_text(payload->'target_account_ids') v WHERE v=:acc)"
                    ).bindparams(pid=pid, acc=acc)
                )
            ).scalar()
            ok = "OK" if m_new == m_old else "*** MISMATCH ***"
            print(f"    pid={pid} acc={acc} scalar={m_new} array={m_old} {ok}")

        # 3) scalar account-lock claim 쿼리 문법/실행 (commit 안 함)
        claimed = (
            await s.execute(
                text(
                    "SELECT id FROM samba_jobs WHERE status='pending' AND job_type='autotune_transmit' "
                    "AND (NOT EXISTS (SELECT 1 FROM samba_jobs r WHERE r.status='running' "
                    "AND r.job_type='autotune_transmit' AND r.id<>samba_jobs.id "
                    "AND (r.payload->'target_account_ids'->>0)=(samba_jobs.payload->'target_account_ids'->>0))) "
                    "ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED"
                )
            )
        ).first()
        print(f"[3] scalar account-lock claim 쿼리 실행 OK (claimed={claimed})")

        await s.rollback()
        print("rollback 완료 — 쓰기 없음")


if __name__ == "__main__":
    asyncio.run(main())
