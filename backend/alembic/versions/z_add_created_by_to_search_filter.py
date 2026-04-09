"""검색그룹에 created_by 컬럼 추가 — 생성자 추적"""

from typing import Sequence, Union
from alembic import op

revision: str = "z_add_created_by"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS — 프로덕션 DB에서 중복 실행 안전
    op.execute(
        "ALTER TABLE samba_search_filter ADD COLUMN IF NOT EXISTS created_by TEXT"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE samba_search_filter DROP COLUMN IF EXISTS created_by")
