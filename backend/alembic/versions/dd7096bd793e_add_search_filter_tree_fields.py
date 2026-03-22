"""add_search_filter_tree_fields

Revision ID: dd7096bd793e
Revises: 7b57da114385
Create Date: 2026-03-22 09:54:47.853561

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dd7096bd793e'
down_revision: Union[str, Sequence[str], None] = '7b57da114385'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """검색그룹 트리 구조 필드 추가 + 기존 데이터를 사이트별 폴더 하위로 마이그레이션."""
    # 신규 컬럼
    op.add_column('samba_search_filter', sa.Column('parent_id', sa.Text(), nullable=True))
    op.add_column('samba_search_filter', sa.Column('is_folder', sa.Boolean(), server_default='false', nullable=False))
    op.create_index(op.f('ix_samba_search_filter_parent_id'), 'samba_search_filter', ['parent_id'], unique=False)

    # 기존 검색그룹을 사이트별 폴더 하위로 마이그레이션
    conn = op.get_bind()
    # 1) 사이트별 고유값 추출
    sites = conn.execute(sa.text(
        "SELECT DISTINCT source_site FROM samba_search_filter WHERE is_folder = false"
    )).fetchall()
    for (site,) in sites:
        folder_id = f"sf_folder_{site.lower()}"
        # 2) 사이트 폴더 생성
        conn.execute(sa.text(
            "INSERT INTO samba_search_filter (id, source_site, name, is_folder, exclude_sold_out, is_active, requested_count, created_at, updated_at) "
            "VALUES (:id, :site, :name, true, true, true, 0, NOW(), NOW()) "
            "ON CONFLICT (id) DO NOTHING"
        ), {"id": folder_id, "site": site, "name": site})
        # 3) 기존 그룹을 폴더 하위로 이동
        conn.execute(sa.text(
            "UPDATE samba_search_filter SET parent_id = :folder_id "
            "WHERE source_site = :site AND is_folder = false AND parent_id IS NULL"
        ), {"folder_id": folder_id, "site": site})


def downgrade() -> None:
    """Downgrade schema."""
    # 폴더 하위 그룹의 parent_id 해제
    op.get_bind().execute(sa.text(
        "UPDATE samba_search_filter SET parent_id = NULL WHERE parent_id IS NOT NULL"
    ))
    # 폴더 삭제
    op.get_bind().execute(sa.text(
        "DELETE FROM samba_search_filter WHERE is_folder = true"
    ))
    op.drop_index(op.f('ix_samba_search_filter_parent_id'), table_name='samba_search_filter')
    op.drop_column('samba_search_filter', 'is_folder')
    op.drop_column('samba_search_filter', 'parent_id')
