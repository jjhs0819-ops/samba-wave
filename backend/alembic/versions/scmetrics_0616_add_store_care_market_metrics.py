"""store_care_market_metrics 테이블 (마켓 점수·품절률 스냅샷)

Revision ID: scmetrics_0616
Revises: zzzzzzzz_add_forbidden_word_market
Create Date: 2026-06-16

마켓 판매자 점수·품절률을 파트너/셀러 포털에서 스크래핑해 적재한다.
포털마다 지표가 달라 핵심값은 정규화 컬럼, 원시 전체는 metrics/raw JSON.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "scmetrics_0616"
down_revision: Union[str, Sequence[str], None] = "zzzzzzzz_add_forbidden_word_market"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema (멱등 — CLAUDE.md 규칙: IF NOT EXISTS raw SQL).

    신규 테이블이지만 운영 선반영/재배포에 대비해 IF NOT EXISTS 로 멱등 보장.
    재실행 시 DuplicateTableError 로 배포가 깨지지 않도록 한다.
    """
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS store_care_market_metrics (
            id varchar NOT NULL,
            tenant_id varchar,
            market_type varchar(30) NOT NULL,
            account_id varchar,
            account_label varchar,
            soldout_rate double precision,
            soldout_rate_prev double precision,
            score double precision,
            grade varchar(30),
            penalty integer,
            metrics json,
            raw json,
            period_label varchar(80),
            status varchar(20),
            error text,
            source_url varchar,
            collected_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_store_care_market_metrics_tenant_id "
        "ON store_care_market_metrics (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_store_care_market_metrics_market_type "
        "ON store_care_market_metrics (market_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_store_care_market_metrics_collected_at "
        "ON store_care_market_metrics (collected_at)"
    )


def downgrade() -> None:
    """Downgrade schema (멱등)."""
    op.execute("DROP INDEX IF EXISTS ix_store_care_market_metrics_collected_at")
    op.execute("DROP INDEX IF EXISTS ix_store_care_market_metrics_market_type")
    op.execute("DROP INDEX IF EXISTS ix_store_care_market_metrics_tenant_id")
    op.execute("DROP TABLE IF EXISTS store_care_market_metrics")
