"""merge heads kream live asks brand risk soft delete

Revision ID: 46f3dce0592b
Revises: add_brand_risk_axes_0811, add_brand_restriction_0723_collected_product_soft_delete, kream_live_asks_01
Create Date: 2026-08-15 18:44:25.590725

작성 가이드: backend/alembic/README 참조. 핵심:
- 운영 트래픽 중 ALTER TABLE / CREATE INDEX 는 lock_timeout + retry 패턴 필수
- 모든 SQL 은 idempotent (IF EXISTS / IF NOT EXISTS) 로 작성
- 47k+ 행 UPDATE 는 청크 분할 또는 인덱스 활용 WHERE 좁히기
- CREATE INDEX CONCURRENTLY 는 transaction 외부에서만 실행 가능 → 별도 마이그레이션
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '46f3dce0592b'
down_revision: Union[str, Sequence[str], None] = ('add_brand_risk_axes_0811', 'add_brand_restriction_0723_collected_product_soft_delete', 'kream_live_asks_01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
