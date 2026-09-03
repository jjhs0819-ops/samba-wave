"""주문건 소싱처 최저가 스캔 캐시 테이블 추가 (samba_order_price_scan)

Revision ID: order_price_scan_01
Revises: 46f3dce0592b, zzzzzzzzzzzzzzzzzzzzzzzzzzzz_shipment_created_at_idx2
Create Date: 2026-09-03

주문 상품명에서 추출한 모델코드로 5개 소싱처(MUSINSA/ABCmart/LOTTEON/SSG/THEHYUNDAI)를
검색한 최저가 결과를 주문 1건당 1행으로 캐시한다 (order_id unique, 24시간 캐시).

두 head(46f3dce0592b · shipment_created_at_idx2)를 여기서 합쳐 단일 head 로 만든다.
전부 IF NOT EXISTS — idempotent. downgrade 는 하지 않는다(운영 규칙: downgrade 금지).
"""

from typing import Sequence, Union

from alembic import op


revision: str = "order_price_scan_01"
down_revision: Union[str, Sequence[str], None] = (
    "46f3dce0592b",
    "zzzzzzzzzzzzzzzzzzzzzzzzzzzz_shipment_created_at_idx2",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "samba_order_price_scan"


def upgrade() -> None:
    # 이미 만들어 쓰던 환경이 있을 수 있어 CREATE TABLE IF NOT EXISTS 로 방어
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            order_id TEXT NOT NULL,
            model_code TEXT,
            base_cost DOUBLE PRECISION,
            best_site TEXT,
            best_price DOUBLE PRECISION,
            best_url TEXT,
            results JSONB,
            suspect BOOLEAN NOT NULL DEFAULT false,
            error TEXT,
            scanned_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )

    # 과거에 일부 컬럼만 있는 환경 대비 — ADD COLUMN IF NOT EXISTS 방어
    for ddl in (
        "tenant_id TEXT",
        "order_id TEXT",
        "model_code TEXT",
        "base_cost DOUBLE PRECISION",
        "best_site TEXT",
        "best_price DOUBLE PRECISION",
        "best_url TEXT",
        "results JSONB",
        "suspect BOOLEAN NOT NULL DEFAULT false",
        "error TEXT",
        "scanned_at TIMESTAMP WITH TIME ZONE",
        "created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()",
        "updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()",
    ):
        op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS {ddl}")

    # 인덱스 — tenant 조회용 + order_id 유니크(주문 1건당 1행, upsert 기준)
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_tenant_id ON {_TABLE} (tenant_id)"
    )
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{_TABLE}_order_id ON {_TABLE} (order_id)"
    )


def downgrade() -> None:
    # 운영 규칙상 downgrade 하지 않는다
    pass
