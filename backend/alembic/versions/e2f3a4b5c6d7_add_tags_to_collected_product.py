"""add_tags_to_collected_product

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-03-17 19:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """수집상품에 태그 컬럼 추가."""
    op.add_column(
        "samba_collected_product",
        sa.Column("tags", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """롤백."""
    op.drop_column("samba_collected_product", "tags")
