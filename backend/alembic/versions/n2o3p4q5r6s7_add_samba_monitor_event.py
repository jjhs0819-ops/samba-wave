"""samba_monitor_event 테이블 생성

Revision ID: n2o3p4q5r6s7
Revises: m1n2o3p4q5r6
Create Date: 2026-03-19 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "n2o3p4q5r6s7"
down_revision: Union[str, Sequence[str], None] = "m1n2o3p4q5r6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """samba_monitor_event 테이블 + 인덱스 생성."""
    op.create_table(
        "samba_monitor_event",
        sa.Column("id", sa.String(length=30), primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False, server_default="info"),
        sa.Column("source_site", sa.Text(), nullable=True),
        sa.Column("market_type", sa.Text(), nullable=True),
        sa.Column("product_id", sa.Text(), nullable=True),
        sa.Column("product_name", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_samba_monitor_event_event_type", "samba_monitor_event", ["event_type"]
    )
    op.create_index(
        "ix_samba_monitor_event_created_at", "samba_monitor_event", ["created_at"]
    )
    op.create_index(
        "ix_samba_monitor_event_product_id", "samba_monitor_event", ["product_id"]
    )


def downgrade() -> None:
    """samba_monitor_event 테이블 삭제."""
    op.drop_index("ix_samba_monitor_event_product_id", "samba_monitor_event")
    op.drop_index("ix_samba_monitor_event_created_at", "samba_monitor_event")
    op.drop_index("ix_samba_monitor_event_event_type", "samba_monitor_event")
    op.drop_table("samba_monitor_event")
