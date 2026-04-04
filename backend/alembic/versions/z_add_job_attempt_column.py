"""samba_jobs에 attempt 컬럼 추가 — 배포 vs OOM 구분용

Revision ID: z_job_attempt_001
Revises: z_catchup_001
Create Date: 2026-04-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "z_job_attempt_001"
down_revision: Union[str, Sequence[str]] = "z_catchup_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "samba_jobs",
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=True),
    )


def downgrade() -> None:
    op.drop_column("samba_jobs", "attempt")
