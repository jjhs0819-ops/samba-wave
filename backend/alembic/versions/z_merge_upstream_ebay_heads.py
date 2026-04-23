"""merge upstream heads with ebay chain

Revision ID: z_merge_up_ebay_01
Revises: 91c5a0e05167, 7e5d4147a01c
Create Date: 2026-04-13 20:00:00.000000

업스트림(91c5a0e05167)과 eBay 포크 체인(7e5d4147a01c)의
alembic head를 병합하는 no-op revision.
"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "z_merge_up_ebay_01"
down_revision: Union[str, Sequence[str], None] = (
    "91c5a0e05167",
    "7e5d4147a01c",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
