"""SambaSearchFilter에 source_brand_name 컬럼 추가

Revision ID: z_add_source_brand_001
Revises: z_fix_autotune_001
Create Date: 2026-04-09

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "z_add_source_brand_001"
down_revision: Union[str, Sequence[str]] = "z_fix_autotune_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS — 프로덕션 DB에서 중복 실행 안전
    op.execute(
        "ALTER TABLE samba_search_filter "
        "ADD COLUMN IF NOT EXISTS source_brand_name TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE samba_search_filter DROP COLUMN IF EXISTS source_brand_name"
    )
