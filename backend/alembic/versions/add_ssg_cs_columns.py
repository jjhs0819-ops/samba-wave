"""samba_cs_inquiry에 SSG 연동 컬럼 추가 — account_id, external_id, external_sent

Revision ID: add_ssg_cs_columns
Revises: None
Create Date: 2026-04-07
"""

from alembic import op

revision = "add_ssg_cs_columns"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE samba_cs_inquiry "
        "ADD COLUMN IF NOT EXISTS account_id TEXT, "
        "ADD COLUMN IF NOT EXISTS external_id TEXT, "
        "ADD COLUMN IF NOT EXISTS external_sent BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_cs_inquiry_account_id ON samba_cs_inquiry (account_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_cs_inquiry_external_id ON samba_cs_inquiry (external_id)"
    )


def downgrade() -> None:
    pass
