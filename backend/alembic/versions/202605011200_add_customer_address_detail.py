"""samba_order에 customer_address_detail 컬럼 추가 (상세주소 분리 저장)

Revision ID: 202605011200_addr_detail
Revises: 202604301200_login_default
Create Date: 2026-05-01 12:00:00.000000

배경:
- 롯데ON, 스마트스토어, 쿠팡, 11번가 API는 기본주소/상세주소를 분리해서 제공하는데,
  기존 코드는 공백 한 칸으로 join해 단일 customer_address에 저장 → 프론트에서 다시
  휴리스틱으로 쪼개야 했고 LotteON 등에서 분리 복사가 실패함.
- 본 마이그레이션은 customer_address_detail 컬럼을 추가해 상세주소를 별도 저장한다.
- customer_address에는 base만 저장(파서 수정으로). 분리 미제공 마켓(eBay, 플레이오토 EMP)
  은 customer_address_detail이 NULL로 유지되며, 프론트는 NULL이면 기존 휴리스틱 fallback.

idempotent 보장 — `op.add_column` 대신 raw SQL `ADD COLUMN IF NOT EXISTS` 사용
(CLAUDE.md "마이그레이션 idempotent 필수" 규칙 준수, blue 무한 재시작 방지).
"""

from typing import Sequence, Union

from alembic import op


revision: str = "202605011200_addr_detail"
down_revision: Union[str, Sequence[str], None] = "202604301200_login_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE samba_order ADD COLUMN IF NOT EXISTS customer_address_detail TEXT"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE samba_order DROP COLUMN IF EXISTS customer_address_detail")
