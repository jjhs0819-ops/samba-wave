"""samba_shipment.created_at 인덱스 — 전송관리 목록 순차스캔 제거

전송관리 화면(GET /api/v1/samba/shipments)은 ORDER BY created_at DESC
LIMIT 50 으로 조회하는데 인덱스가 없었다. 운영 실측(2026-08-19, 710만 행):
  적용 전 : Parallel Seq Scan, 버퍼 450,355개(3.5GB)
  적용 후 : Index Scan, 버퍼 53개 / 0.433ms

★ CONCURRENTLY 를 쓰지 않는다. 이 저장소에서는 마이그레이션 안에서 쓸 수 없다 —
alembic/env.py 의 do_run_migrations 가 첫 줄에서 `SET lock_timeout` 을 실행해
커넥션에 트랜잭션이 autobegin 되고, alembic 1.17 의 begin_transaction() 은
외부 트랜잭션이 있으면 nullcontext 를 반환해 _transaction 을 만들지 않는다.
그 상태로 op.get_context().autocommit_block() 을 부르면 assert 로 죽는다
(2026-08-19 배포 중 이걸로 API 기동 실패 502 발생).

운영 DB 에는 psql 로 CREATE INDEX CONCURRENTLY 를 직접 실행해 이미 만들어 뒀으므로
이 마이그레이션은 IF NOT EXISTS 로 즉시 no-op 이다. 신규 환경은 테이블이 비어 있어
일반 CREATE INDEX 의 락 부담이 없다. 대용량 테이블에 뒤늦게 적용하는 경우에는
반드시 psql 로 CONCURRENTLY 를 먼저 돌린 뒤 이 마이그레이션을 태울 것.

Revision ID: zzzzzzzzzzzzzzzzzzzzzzzzzzzz_shipment_created_at_idx2
Revises: remove_sns_posting_0802
Create Date: 2026-08-19
"""

from typing import Sequence, Union

from alembic import op

revision: str = "zzzzzzzzzzzzzzzzzzzzzzzzzzzz_shipment_created_at_idx2"
down_revision: Union[str, Sequence[str], None] = "remove_sns_posting_0802"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_shipment_created_at "
        "ON samba_shipment (created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_samba_shipment_created_at")
