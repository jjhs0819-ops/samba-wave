"""name_rule에 replace_mode, name_composition, brand_display, dedup_enabled 추가

Revision ID: 2d01eadc676b
Revises: f3a4b5c6d7e8
Create Date: 2026-03-18 19:33:17.472942

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2d01eadc676b"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "samba_name_rule",
        sa.Column(
            "replace_mode", sa.Text(), server_default="simultaneous", nullable=False
        ),
    )
    op.add_column(
        "samba_name_rule", sa.Column("name_composition", sa.JSON(), nullable=True)
    )
    op.add_column(
        "samba_name_rule",
        sa.Column(
            "brand_display",
            sa.Text(),
            server_default="show_at_position",
            nullable=False,
        ),
    )
    op.add_column(
        "samba_name_rule",
        sa.Column(
            "dedup_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("samba_name_rule", "dedup_enabled")
    op.drop_column("samba_name_rule", "brand_display")
    op.drop_column("samba_name_rule", "name_composition")
    op.drop_column("samba_name_rule", "replace_mode")
