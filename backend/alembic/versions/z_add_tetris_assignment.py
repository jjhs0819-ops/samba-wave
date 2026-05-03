"""samba_tetris_assignment 테이블 추가

Revision ID: z_add_tetris_assignment
Revises:
Create Date: 2026-05-03 12:00:00.000000

z_ 독립 브랜치 — IF NOT EXISTS 사용으로 idempotent 보장.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "z_add_tetris_assignment"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS samba_tetris_assignment (
            id VARCHAR NOT NULL PRIMARY KEY,
            tenant_id VARCHAR,
            source_site VARCHAR NOT NULL,
            brand_name VARCHAR NOT NULL,
            market_account_id VARCHAR NOT NULL,
            policy_id VARCHAR,
            position_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tetris_tenant "
        "ON samba_tetris_assignment (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tetris_account "
        "ON samba_tetris_assignment (market_account_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tetris_site "
        "ON samba_tetris_assignment (source_site)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS samba_tetris_assignment")
