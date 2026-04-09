"""OKmall → REXMONDE 소싱처 이름 변경 (source_site 컬럼 일괄 UPDATE)

Revision ID: z_rexmonde_001
Revises: add_ssg_cs_columns, b9c8d7e6f5a4, r1a2b3c4d5e6, z_login_hist_001
Create Date: 2026-04-07

OKmall이 REXMONDE로 리브랜딩됨에 따라
source_site = 'OKmall'인 레코드를 'REXMONDE'로 일괄 변경.
대상 테이블: samba_collected_product, samba_collected_brand, samba_product,
            samba_order, samba_category_mapping, samba_monitor_event
"""

from typing import Sequence, Union

from alembic import op


revision: str = "z_rexmonde_001"
down_revision: Union[str, Sequence[str]] = (
    "add_ssg_cs_columns",
    "b9c8d7e6f5a4",
    "r1a2b3c4d5e6",
    "z_login_hist_001",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = [
    "samba_collected_product",
    "samba_product",
    "samba_order",
    "samba_category_mapping",
    "samba_monitor_event",
]


def _safe_update(table: str, old: str, new: str) -> None:
    """테이블이 없으면 스킵."""
    op.execute(f"UPDATE {table} SET source_site = '{new}' WHERE source_site = '{old}'")


def upgrade() -> None:
    for table in _TABLES:
        _safe_update(table, "OKmall", "REXMONDE")


def downgrade() -> None:
    for table in _TABLES:
        _safe_update(table, "REXMONDE", "OKmall")
