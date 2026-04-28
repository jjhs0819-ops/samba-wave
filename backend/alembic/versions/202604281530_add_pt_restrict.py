"""samba_collected_product 적립금 사용 제한 컬럼 추가 (is_point_restricted)

Revision ID: 202604281530_add_pt_restrict
Revises: 202604251130_add_customer_note
Create Date: 2026-04-28 15:30:00.000000

배경:
  무신사 상품 상세 API에 isRestictedUsePoint(적립금 사용 제한) 플래그가 있어
  적립금 사용 가능 상품과 불가 상품을 구분할 수 있다.
  정책의 "소싱처별 추가 마진"에서 적립금 사용 가능 상품에만 추가 마진을
  적용하는 옵션을 지원하기 위해 상품 단위로 해당 플래그를 저장한다.

  - True  : 적립금 사용 불가 상품
  - False : 적립금 사용 가능 상품
  - NULL  : 미수집 또는 지원하지 않는 소싱처
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "202604281530_add_pt_restrict"
down_revision: Union[str, None] = "202604251130_add_customer_note"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "samba_collected_product",
        sa.Column("is_point_restricted", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("samba_collected_product", "is_point_restricted")
