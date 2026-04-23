"""merge ebay chain with dedup_default_true

Revision ID: zz_merge_ebay_and_dedup
Revises: 202604232300_dedup_default_true, z_merge_up_ebay_01
Create Date: 2026-04-24 00:00:00.000000

eBay 포크 체인(z_merge_up_ebay_01)과 main의 dedup 기본값 변경(202604232300_dedup_default_true)
두 head를 병합하는 no-op revision.
"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "zz_merge_ebay_and_dedup"
down_revision: Union[str, Sequence[str], None] = (
    "202604232300_dedup_default_true",
    "z_merge_up_ebay_01",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
