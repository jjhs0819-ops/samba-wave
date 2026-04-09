"""SambaSearchFilter에 source_brand_name 컬럼 추가

Revision ID: z_add_source_brand_001
Revises: z_fix_autotune_001
Create Date: 2026-04-09

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "z_add_source_brand_001"
down_revision: Union[str, Sequence[str]] = "z_fix_autotune_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "samba_search_filter",
        sa.Column("source_brand_name", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("samba_search_filter", "source_brand_name")
