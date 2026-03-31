"""merge multiple heads

Revision ID: s7t8u9v0w1x2
Revises: f71132fc5b81, r6s7t8u9v0w1
Create Date: 2026-03-26

"""
from typing import Sequence, Union

revision: str = 's7t8u9v0w1x2'
down_revision: Union[str, Sequence[str], None] = ('f71132fc5b81', 'r6s7t8u9v0w1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
