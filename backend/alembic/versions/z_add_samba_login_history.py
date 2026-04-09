"""samba_login_history 테이블 추가

Revision ID: z_login_hist_001
Revises: z_catchup_001
Create Date: 2026-04-07
"""

from typing import Sequence, Union

from alembic import op

revision: str = "z_login_hist_001"
down_revision: Union[str, Sequence[str]] = ("z_add_paid_at", "z_add_created_by")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS samba_login_history (
            id VARCHAR(30) PRIMARY KEY,
            user_id TEXT NOT NULL,
            email TEXT NOT NULL,
            ip_address TEXT,
            region TEXT,
            user_agent TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_samba_login_history_user_id
        ON samba_login_history (user_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_samba_login_history_created_at
        ON samba_login_history (created_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS samba_login_history")
