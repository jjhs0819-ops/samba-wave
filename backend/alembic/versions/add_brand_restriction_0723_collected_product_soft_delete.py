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
"""

from alembic import op


revision = "add_brand_restriction_0723_collected_product_soft_delete"
down_revision = "remove_sns_posting_0802"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE samba_collected_product "
        "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL"
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
