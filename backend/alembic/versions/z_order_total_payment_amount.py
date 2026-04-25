"""samba_order 고객결제금액 컬럼 추가 (total_payment_amount)

Revision ID: z_order_total_payment
Revises: z_warroom_dashboard_idx
Create Date: 2026-04-25 16:00:00.000000

배경:
  롯데ON 정산예정금액이 우리 화면(44,724)과 샵마인(46,814)이 달랐던 이유는,
  기존 코드가 "총판매금액(sale_price)"과 "고객결제금액"을 구분 없이 같은 컬럼으로 다루고
  정산 추정 공식에서 셀러부담할인을 두 번 차감하는 버그가 있었기 때문.

  본 마이그레이션은 고객결제금액(total_payment_amount) 컬럼을 추가해
  UI/통계에서 샵마인 기준 "고객결제금액"을 정확히 표시할 수 있게 한다.

  롯데ON: total_payment_amount = slAmt - fvrAmtSum
  다른 마켓: 당분간 NULL → UI에서 sale_price로 폴백
"""

from typing import Sequence, Union

from alembic import op


revision: str = "z_order_total_payment"
down_revision: Union[str, None] = "z_warroom_dashboard_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS로 재실행 안전 보장
    op.execute(
        "ALTER TABLE samba_order ADD COLUMN IF NOT EXISTS total_payment_amount DOUBLE PRECISION"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE samba_order DROP COLUMN IF EXISTS total_payment_amount")
