"""롯데ON 교환 클레임 status 잘못 매핑된 기존 데이터 보정

Revision ID: 202605011300_fix_lotteon_exchange
Revises: 202605011200_addr_detail
Create Date: 2026-05-01

이전 코드(order.py)에서 롯데ON 교환 클레임(odPrgsStepCd 21/22/23)을
status='return_requested'(반품요청)으로 잘못 저장하던 버그가 있었음.
본 마이그레이션은 shipping_status가 교환 단계인데 status가 return_requested인
기존 행을 올바른 exchanging/exchanged 로 보정한다.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "202605011300_fix_lotteon_exchange"
down_revision: Union[str, Sequence[str]] = "202605011200_addr_detail"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE samba_order
        SET status = CASE
            WHEN shipping_status = '교환완료' THEN 'exchanged'
            ELSE 'exchanging'
        END
        WHERE source = 'lotteon'
          AND status = 'return_requested'
          AND shipping_status IN ('교환요청','교환회수완료','교환재배송','교환완료')
        """
    )


def downgrade() -> None:
    pass
