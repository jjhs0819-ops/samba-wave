"""dedup_enabled 기본값을 false에서 true로 변경

Revision ID: 202604232300_dedup_default_true
Revises: z_products_search_perf_idx
Create Date: 2026-04-23 23:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "202604232300_dedup_default_true"
down_revision: Union[str, Sequence[str], None] = "z_products_search_perf_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. server_default 변경
    op.alter_column(
        "samba_name_rule",
        "dedup_enabled",
        existing_type=sa.Boolean(),
        server_default="true",
        existing_server_default="false",
    )
    # 2. 기존 레코드 중 dedup_enabled=false인 것을 true로 변경
    op.execute(
        "UPDATE samba_name_rule SET dedup_enabled = true WHERE dedup_enabled = false"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 1. 기존 값으로 복원
    op.execute(
        "UPDATE samba_name_rule SET dedup_enabled = false WHERE dedup_enabled = true"
    )
    # 2. server_default 복원
    op.alter_column(
        "samba_name_rule",
        "dedup_enabled",
        existing_type=sa.Boolean(),
        server_default="false",
        existing_server_default="true",
    )
