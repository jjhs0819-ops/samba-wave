"""Add samba_ebay_mapping table

Revision ID: z_add_samba_ebay_mapping
Revises:
Create Date: 2026-04-10

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "z_add_samba_ebay_mapping"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("samba_ebay_mapping"):
        return

    op.create_table(
        "samba_ebay_mapping",
        sa.Column("id", sa.String(length=30), primary_key=True),
        sa.Column("tenant_id", sa.String, nullable=True, index=True),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("kr_value", sa.Text, nullable=False),
        sa.Column("en_value", sa.Text, nullable=False),
        sa.Column(
            "source",
            sa.Text,
            nullable=False,
            server_default="default",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("category", "kr_value", name="uq_sem_category_kr"),
    )
    op.create_index("ix_sem_category", "samba_ebay_mapping", ["category"])


def downgrade() -> None:
    op.drop_index("ix_sem_category", table_name="samba_ebay_mapping")
    op.drop_table("samba_ebay_mapping")
