"""add_board_no_to_samba_cs_inquiry

Revision ID: c4f2407a01
Revises: z3a4b5c6d7e8
Create Date: 2026-04-07 18:30:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c4f2407a01"
down_revision: Union[str, Sequence[str], None] = "z3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 카페24 게시판 article 답변 시 필요한 board_no 컬럼 추가
    op.execute("ALTER TABLE samba_cs_inquiry ADD COLUMN IF NOT EXISTS board_no TEXT")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE samba_cs_inquiry DROP COLUMN IF EXISTS board_no")
