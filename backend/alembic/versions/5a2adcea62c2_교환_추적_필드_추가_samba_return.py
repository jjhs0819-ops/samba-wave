"""교환 추적 필드 추가 samba_return

Revision ID: 5a2adcea62c2
Revises: z_catchup_001
Create Date: 2026-04-03 19:25:45.955887

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5a2adcea62c2'
down_revision: Union[str, Sequence[str], None] = 'z_catchup_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """교환 추적 필드를 samba_return 테이블에 추가."""
    # 11번가 클레임 API 식별자 (교환 승인/거부 호출에 필요)
    op.add_column('samba_return', sa.Column('clm_req_seq', sa.Text(), nullable=True))
    op.add_column('samba_return', sa.Column('ord_prd_seq', sa.Text(), nullable=True))

    # 교환 상품 회수 추적 (수기 입력)
    op.add_column('samba_return', sa.Column('exchange_retrieval_status', sa.Text(), nullable=True))
    op.add_column('samba_return', sa.Column('exchange_retrieved_at', sa.DateTime(timezone=True), nullable=True))

    # 소싱처 재출고 정보 (수기 입력)
    op.add_column('samba_return', sa.Column('exchange_reship_company', sa.Text(), nullable=True))
    op.add_column('samba_return', sa.Column('exchange_reship_tracking', sa.Text(), nullable=True))

    # 고객 도착 일자 (수기 입력)
    op.add_column('samba_return', sa.Column('exchange_delivered_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """교환 추적 필드를 samba_return 테이블에서 제거."""
    op.drop_column('samba_return', 'exchange_delivered_at')
    op.drop_column('samba_return', 'exchange_reship_tracking')
    op.drop_column('samba_return', 'exchange_reship_company')
    op.drop_column('samba_return', 'exchange_retrieved_at')
    op.drop_column('samba_return', 'exchange_retrieval_status')
    op.drop_column('samba_return', 'ord_prd_seq')
    op.drop_column('samba_return', 'clm_req_seq')
