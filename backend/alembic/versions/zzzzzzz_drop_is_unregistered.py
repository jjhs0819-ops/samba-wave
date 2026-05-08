"""is_unregistered 컬럼 제거 — registered_accounts 배열을 단일 등록 기준으로 통일

is_unregistered(boolean)와 registered_accounts(JSONB)가 동일한 개념을 중복 표현하면서
일부 코드 경로(PlayAuto 싱크, 롯데홈 플러그인 등)가 한쪽만 업데이트해 불일치 발생.
registered_accounts를 단일 기준으로 사용하고 표현식 인덱스로 성능 보완.

Revision ID: zzzzzzz_drop_is_unregistered
Revises: zzzzzz_lotteon_order_dedup_fix
Create Date: 2026-05-08 00:00:00.000000
"""

from alembic import op

revision = "zzzzzzz_drop_is_unregistered"
down_revision = "dd3eaff7233e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # registered_accounts가 비어있지 않은 상품을 빠르게 필터링하는 표현식 인덱스
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scp_has_registered_accounts
        ON samba_collected_product (
            (registered_accounts IS NOT NULL AND registered_accounts != '[]'::jsonb)
        )
    """)

    # is_unregistered 컬럼 및 기존 B-tree 인덱스 제거
    op.execute("""
        DROP INDEX IF EXISTS ix_samba_collected_product_is_unregistered
    """)
    op.execute("""
        ALTER TABLE samba_collected_product DROP COLUMN IF EXISTS is_unregistered
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE samba_collected_product
        ADD COLUMN IF NOT EXISTS is_unregistered BOOLEAN NOT NULL DEFAULT TRUE
    """)
    op.execute("""
        UPDATE samba_collected_product
        SET is_unregistered = NOT (
            registered_accounts IS NOT NULL AND registered_accounts != '[]'::jsonb
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_samba_collected_product_is_unregistered
        ON samba_collected_product (is_unregistered)
    """)
    op.execute("""
        DROP INDEX IF EXISTS ix_scp_has_registered_accounts
    """)
