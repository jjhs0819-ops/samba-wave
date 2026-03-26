"""samba_return 모델 동기화 (customer_phone, check_date 이미 존재)

Revision ID: 4c81abda9e0e
Revises: 7e43adcea6e8
Create Date: 2026-03-26 08:34:51.181679

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '4c81abda9e0e'
down_revision: Union[str, Sequence[str], None] = '7e43adcea6e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """컬럼이 이미 DB에 존재하므로 모델 동기화만."""
    pass


def downgrade() -> None:
    pass
