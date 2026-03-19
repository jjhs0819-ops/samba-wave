"""add_detail_template_image_s3_keys

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-03-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "samba_detail_template",
        sa.Column("top_image_s3_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "samba_detail_template",
        sa.Column("bottom_image_s3_key", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("samba_detail_template", "bottom_image_s3_key")
    op.drop_column("samba_detail_template", "top_image_s3_key")
