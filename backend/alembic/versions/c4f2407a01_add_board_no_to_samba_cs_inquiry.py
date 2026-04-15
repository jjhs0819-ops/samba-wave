"""add_board_no_to_samba_cs_inquiry

Revision ID: c4f2407a01
Revises: 26dd9b23892a
Create Date: 2026-04-07 18:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4f2407a01"
down_revision: Union[str, Sequence[str], None] = "26dd9b23892a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 카페24 게시판 article 답변 시 필요한 board_no 컬럼 추가
    op.add_column(
        "samba_cs_inquiry",
        sa.Column("board_no", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("samba_cs_inquiry", "board_no")
