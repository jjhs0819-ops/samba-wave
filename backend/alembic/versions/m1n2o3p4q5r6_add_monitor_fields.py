"""모니터링 필드 추가 (monitor_priority, last_refreshed_at, refresh_error_count)

Revision ID: m1n2o3p4q5r6
Revises: a1b2c3d4e5f6
Create Date: 2026-03-18 23:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "m1n2o3p4q5r6"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """모니터링 필드 추가."""
    op.add_column(
        "samba_collected_product",
        sa.Column("monitor_priority", sa.Text(), server_default="cold", nullable=False),
    )
    op.add_column(
        "samba_collected_product",
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "samba_collected_product",
        sa.Column(
            "refresh_error_count", sa.Integer(), server_default="0", nullable=False
        ),
    )


def downgrade() -> None:
    """모니터링 필드 제거."""
    op.drop_column("samba_collected_product", "refresh_error_count")
    op.drop_column("samba_collected_product", "last_refreshed_at")
    op.drop_column("samba_collected_product", "monitor_priority")
