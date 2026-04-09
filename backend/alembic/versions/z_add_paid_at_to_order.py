"""samba_order에 paid_at(고객결제시간) 컬럼 추가

Revision ID: z_add_paid_at
Revises: z_job_attempt_001
Create Date: 2026-04-06
"""

from typing import Sequence, Union

from alembic import op

revision: str = "z_add_paid_at"
down_revision: Union[str, Sequence[str]] = "z_job_attempt_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE samba_order ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ")


def downgrade() -> None:
    op.drop_column("samba_order", "paid_at")
