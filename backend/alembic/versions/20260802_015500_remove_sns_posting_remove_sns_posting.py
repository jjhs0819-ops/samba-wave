"""SNS마케팅(sns_posting) 기능 제거 — 미사용(전 테이블 0건) 기능 삭제

Revision ID: remove_sns_posting_0802
Revises: add_brand_restriction_0723
Create Date: 2026-08-02

개발예정 상태로 실사용 없이 방치되던 SNS마케팅 탭/도메인 코드 전체 제거.
samba_wp_site, samba_sns_keyword_group, samba_sns_post, samba_sns_auto_config
4개 테이블 전부 0건 확인 후 삭제.
"""

import sqlalchemy as sa
from alembic import op

revision = "remove_sns_posting_0802"
down_revision = "add_brand_restriction_0723"
branch_labels = None
depends_on = None

TABLES = [
    "samba_sns_post",
    "samba_sns_keyword_group",
    "samba_sns_auto_config",
    "samba_wp_site",
]


def _has_table(table: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
        {"t": table},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    for t in TABLES:
        if _has_table(t):
            op.drop_table(t)


def downgrade() -> None:
    # 기능 자체를 제거하는 마이그레이션 — 되돌릴 스키마 정의가 코드에서 삭제됨.
    # 필요 시 git history의 sns_posting/model.py 참고해 수동 복원.
    pass
