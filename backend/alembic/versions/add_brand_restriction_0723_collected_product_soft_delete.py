"""samba_collected_product 소프트 삭제(휴지통) 컬럼 추가

배경:
- 수집상품 삭제가 지금까지는 하드 삭제(행 자체 제거)만 있었음.
- 정책적용 flat 테이블의 "저장상품/휴지통(누적매출)" 컬럼을 위해
  복구 가능한 소프트 삭제(휴지통)를 새로 도입한다.

Revision ID: add_brand_restriction_0723_collected_product_soft_delete
Revises: remove_sns_posting_0802
Create Date: 2026-07-28

[2026-08-10] down_revision 재연결 — 원래 add_brand_restriction_0723 을 가리켰으나
본진이 그 뒤로 전진해 head 가 2개로 갈렸다(CI 는 head 1개를 강제한다).
본진 최신 head(remove_sns_posting_0802) 뒤에 붙여 단일 체인으로 되돌린다.
컬럼 추가/인덱스 생성 모두 IF NOT EXISTS 라 순서가 바뀌어도 안전하다.

[2026-08-12] upgrade() 재작성 — samba_collected_product 는 hot 테이블이라
'IF NOT EXISTS' 만 믿고 바로 ALTER 하면 순간 ACCESS EXCLUSIVE 락이 활성
트랜잭션과 데드락 날 수 있다(zzzzzzzzzzzzzzzz_add_addon_options.py 동일 패턴).
information_schema 로 컬럼 존재를 먼저 확인해 있으면 ALTER 자체를 스킵하고,
없을 때만 idle in transaction 정리 + lock_timeout 을 걸고 실행한다.
"""

from alembic import op
from sqlalchemy import text


revision = "add_brand_restriction_0723_collected_product_soft_delete"
down_revision = "remove_sns_posting_0802"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'samba_collected_product' "
            "AND column_name = 'deleted_at'"
        )
    ).fetchone()
    if not exists:
        # 누락 컬럼일 때만 idle 정리 + ALTER 실행 (hot 테이블 데드락 방지)
        op.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE state = 'idle in transaction'
              AND pid <> pg_backend_pid()
            """
        )
        op.execute("SET LOCAL lock_timeout = '5min'")
        op.execute(
            "ALTER TABLE samba_collected_product ADD COLUMN deleted_at TIMESTAMPTZ NULL"
        )

    # hot 테이블 — CONCURRENTLY로 락 회피, 트랜잭션 밖에서 실행
    op.execute("COMMIT")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_samba_collected_product_deleted_at ON samba_collected_product (deleted_at)"
    )


def downgrade() -> None:
    # hot 테이블 — CONCURRENTLY로 락 회피, 트랜잭션 밖에서 실행
    op.execute("COMMIT")
    op.execute(
        "DROP INDEX CONCURRENTLY IF EXISTS ix_samba_collected_product_deleted_at"
    )
    op.execute("ALTER TABLE samba_collected_product DROP COLUMN IF EXISTS deleted_at")
