"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

작성 가이드: backend/alembic/README 참조. 핵심:
- 운영 트래픽 중 ALTER TABLE / CREATE INDEX 는 lock_timeout + retry 패턴 필수
- 모든 SQL 은 idempotent (IF EXISTS / IF NOT EXISTS) 로 작성
- 47k+ 행 UPDATE 는 청크 분할 또는 인덱스 활용 WHERE 좁히기
- CREATE INDEX CONCURRENTLY 는 transaction 외부에서만 실행 가능 → 별도 마이그레이션
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """Upgrade schema."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade schema."""
    ${downgrades if downgrades else "pass"}
