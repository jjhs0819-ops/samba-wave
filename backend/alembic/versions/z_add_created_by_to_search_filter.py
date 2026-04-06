"""검색그룹에 created_by 컬럼 추가 — 생성자 추적"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "z_add_created_by"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "samba_search_filter", sa.Column("created_by", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("samba_search_filter", "created_by")
