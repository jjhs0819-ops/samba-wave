"""검색그룹에 target_mappings 컬럼 추가"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "v1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "bcb782b5afaa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "samba_search_filter", sa.Column("target_mappings", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("samba_search_filter", "target_mappings")
