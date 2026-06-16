"""store_care_market_metrics 테이블 (마켓 점수·품절률 스냅샷)

Revision ID: scmetrics_0616
Revises: zzzzzzzz_add_forbidden_word_market
Create Date: 2026-06-16

마켓 판매자 점수·품절률을 파트너/셀러 포털에서 스크래핑해 적재한다.
포털마다 지표가 달라 핵심값은 정규화 컬럼, 원시 전체는 metrics/raw JSON.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "scmetrics_0616"
down_revision: Union[str, Sequence[str], None] = "zzzzzzzz_add_forbidden_word_market"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "store_care_market_metrics",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("market_type", sa.String(length=30), nullable=False),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("account_label", sa.String(), nullable=True),
        sa.Column("soldout_rate", sa.Float(), nullable=True),
        sa.Column("soldout_rate_prev", sa.Float(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("grade", sa.String(length=30), nullable=True),
        sa.Column("penalty", sa.Integer(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("period_label", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_store_care_market_metrics_tenant_id"),
        "store_care_market_metrics",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_store_care_market_metrics_market_type"),
        "store_care_market_metrics",
        ["market_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_store_care_market_metrics_collected_at"),
        "store_care_market_metrics",
        ["collected_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_store_care_market_metrics_collected_at"),
        table_name="store_care_market_metrics",
    )
    op.drop_index(
        op.f("ix_store_care_market_metrics_market_type"),
        table_name="store_care_market_metrics",
    )
    op.drop_index(
        op.f("ix_store_care_market_metrics_tenant_id"),
        table_name="store_care_market_metrics",
    )
    op.drop_table("store_care_market_metrics")
