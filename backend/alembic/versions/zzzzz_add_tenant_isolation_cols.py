"""테넌트 격리 컬럼 추가 — CS문의/연락로그/판매처/로그인이력 tenant_id

멀티테넌시 데이터 격리 누락 사고 대응:
samba_cs_inquiry / samba_contact_log / samba_channel / samba_login_history
4개 테이블에 tenant_id 컬럼이 없어 ORM 자동 tenant 필터(tenant_filter.py)가
적용되지 않아 전 테넌트 데이터가 한 통에 노출되던 문제를 해결한다.

전부 소형 테이블(<400행)이라 일반 인덱스로 충분(CONCURRENTLY 불필요).
idempotent: information_schema 가드 + ADD COLUMN IF NOT EXISTS.

Revision ID: zzzzz_add_tenant_isolation_cols
Revises: zzzz_name_rule_mkt_prefix_001
Create Date: 2026-06-09
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "zzzzz_add_tenant_isolation_cols"
down_revision = "zzzz_name_rule_mkt_prefix_001"
branch_labels = None
depends_on = None

_TABLES = [
    "samba_cs_inquiry",
    "samba_contact_log",
    "samba_channel",
    "samba_login_history",
]


def upgrade() -> None:
    conn = op.get_bind()
    for tbl in _TABLES:
        # 이미 컬럼이 있으면 ALTER 자체를 스킵 — hot 테이블 AccessExclusiveLock 회피
        exists = conn.exec_driver_sql(
            "SELECT 1 FROM information_schema.columns "
            f"WHERE table_name='{tbl}' AND column_name='tenant_id'"
        ).first()
        if exists:
            continue
        op.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS tenant_id VARCHAR")
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{tbl}_tenant_id ON {tbl} (tenant_id)"
        )


def downgrade() -> None:
    # 데이터 격리 컬럼 제거는 위험 — 무동작(컬럼 유지)
    pass
