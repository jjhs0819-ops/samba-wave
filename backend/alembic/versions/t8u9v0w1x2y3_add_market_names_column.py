"""samba_collected_product에 market_names 컬럼 추가

마켓별 등록 상품명을 별도 관리하기 위한 JSON 컬럼.
예: { "스마트스토어": "나이키 에어맥스 97", "쿠팡": "나이키 에어맥스 97 OG" }

Revision ID: t8u9v0w1x2y3
Revises: s7t8u9v0w1x2
Create Date: 2026-03-27 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "t8u9v0w1x2y3"
down_revision: Union[str, Sequence[str], None] = "s7t8u9v0w1x2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "samba_collected_product", sa.Column("market_names", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("samba_collected_product", "market_names")
