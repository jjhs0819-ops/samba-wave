"""tenant 구독 필드 추가 subscription_start end autotune_enabled

Revision ID: 2d79853b73b9
Revises: z_order_cpid_001
Create Date: 2026-04-13 18:00:50.325048

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "2d79853b73b9"
down_revision: Union[str, Sequence[str], None] = "z_order_cpid_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """samba_tenants 테이블에 구독 관리 컬럼 3개 추가."""
    op.add_column(
        "samba_tenants",
        sa.Column("subscription_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "samba_tenants",
        sa.Column("subscription_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "samba_tenants",
        sa.Column(
            "autotune_enabled", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    """구독 관리 컬럼 3개 롤백."""
    op.drop_column("samba_tenants", "autotune_enabled")
    op.drop_column("samba_tenants", "subscription_end")
    op.drop_column("samba_tenants", "subscription_start")
