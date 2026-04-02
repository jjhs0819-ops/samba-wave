"""samba_search_filter에 ss_brand 관련 컬럼 추가

Revision ID: o3p4q5r6s7t8
Revises: n2o3p4q5r6s7
Create Date: 2026-03-26 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "o3p4q5r6s7t8"
down_revision: Union[str, Sequence[str], None] = "f71132fc5b81"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "samba_search_filter", sa.Column("ss_brand_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "samba_search_filter", sa.Column("ss_brand_name", sa.Text(), nullable=True)
    )
    op.add_column(
        "samba_search_filter",
        sa.Column("ss_manufacturer_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "samba_search_filter",
        sa.Column("ss_manufacturer_name", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("samba_search_filter", "ss_manufacturer_name")
    op.drop_column("samba_search_filter", "ss_manufacturer_id")
    op.drop_column("samba_search_filter", "ss_brand_name")
    op.drop_column("samba_search_filter", "ss_brand_id")
