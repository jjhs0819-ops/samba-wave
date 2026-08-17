"""크림 오토튠 로그 테이블 추가.

크림 섀도/통합 사이클은 진행상황을 kream_refresh_log 에 적재하고, api 프로세스가
tail_kream_logs() 로 읽어 오토튠 화면에 노출한다. 테이블이 없으면 매 사이클
"로그 DB flush 실패(무시)" 만 남고 화면에는 아무것도 안 보인다(기능은 정상 동작).

링버퍼 성격이라 _flush_logs_to_db() 가 최근 1,500행만 남기고 지운다.

Revision ID: kream_refresh_log_01
Revises: add_brand_restriction_0723
"""

from alembic import op
import sqlalchemy as sa

revision = "kream_refresh_log_01"
down_revision = "add_brand_restriction_0723"
branch_labels = None
depends_on = None

_TABLE = "kream_refresh_log"


def upgrade() -> None:
    # 이미 만들어 쓰던 환경(운영/로컬)이 있을 수 있어 존재하면 건너뛴다.
    bind = op.get_bind()
    if sa.inspect(bind).has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        # id 는 정렬·트림·tail(last_id) 기준이라 단조 증가 필수
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("site", sa.Text(), nullable=False, server_default=""),
        sa.Column("product_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("msg", sa.Text(), nullable=False, server_default=""),
        sa.Column("level", sa.Text(), nullable=False, server_default="info"),
        sa.Column("device_id", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
