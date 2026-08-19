"""samba_shipment.created_at 인덱스 추가 — 전송관리 목록 3.5GB 순차스캔 제거

전송관리 화면(GET /api/v1/samba/shipments)은
`ORDER BY created_at DESC LIMIT 50` 으로 조회하는데, samba_shipment 는
2026-08-19 기준 **7,123,114행 / 4.4GB** 이고 created_at 인덱스가 없었다.
운영 실측 결과 50건을 얻으려고 **450,355블록(3.5GB)을 순차스캔**하고 있었다.

CONCURRENTLY 로 만든다 — 이 테이블은 전송 잡이 상시 INSERT/UPDATE 하는
hot 테이블이라, 일반 CREATE INDEX 의 SHARE 락이 수십 초간 전송을 통째로
막는다. CONCURRENTLY 는 트랜잭션 안에서 실행할 수 없어 autocommit 블록을 쓴다.

주의: CONCURRENTLY 는 실패 시 INVALID 인덱스를 남길 수 있다. 그 경우
DROP INDEX 후 재실행하면 된다(IF NOT EXISTS 라 재실행 자체는 안전).

Revision ID: zzzzzzzzzzzzzzzzzzzzzzzzzzz_shipment_created_at_idx
Revises: remove_sns_posting_0802
Create Date: 2026-08-19
"""

from typing import Sequence, Union

from alembic import op

revision: str = "zzzzzzzzzzzzzzzzzzzzzzzzzzz_shipment_created_at_idx"
down_revision: Union[str, Sequence[str], None] = "remove_sns_posting_0802"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # DESC 로 만든다 — 목록이 항상 최신순(created_at DESC)이라 정렬 방향을 맞추면
    # 역방향 스캔 없이 인덱스 선두부터 50건만 읽고 끝난다.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_samba_shipment_created_at ON samba_shipment (created_at DESC)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_samba_shipment_created_at")
