"""소싱처 계정에 is_login_default 컬럼 추가 (자동로그인 기본 계정 플래그)

Revision ID: 202604301200_login_default
Revises: 202604281530_add_pt_restrict, z_order_total_payment
Create Date: 2026-04-30 12:00:00.000000

배경:
- 사이트별 여러 소싱처 계정 중 자동로그인에 사용할 "기본 계정"을 구분하기 위한 플래그.
- 사이트당 1개만 true가 되도록 application 레벨에서 강제 (DB partial unique까지는 미적용).

idempotent 보장 — `op.add_column` 대신 raw SQL `ADD COLUMN IF NOT EXISTS` 사용
(CLAUDE.md "마이그레이션 idempotent 필수" 규칙 준수, blue 무한 재시작 방지).

두 head 병합 — 202604281530_add_pt_restrict + z_order_total_payment.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "202604301200_login_default"
down_revision: Union[str, Sequence[str], None] = (
    "202604281530_add_pt_restrict",
    "z_order_total_payment",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # is_login_default 컬럼 — 자동로그인 기본 계정 플래그
    op.execute(
        """
        ALTER TABLE samba_sourcing_account
        ADD COLUMN IF NOT EXISTS is_login_default BOOLEAN NOT NULL DEFAULT FALSE
        """
    )
    # 인덱스 — site_name + is_login_default 조회 성능
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_samba_sourcing_account_site_login_default
        ON samba_sourcing_account (site_name, is_login_default)
        WHERE is_login_default = TRUE
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_samba_sourcing_account_site_login_default")
    op.execute(
        "ALTER TABLE samba_sourcing_account DROP COLUMN IF EXISTS is_login_default"
    )
