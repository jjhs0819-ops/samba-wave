"""두 alembic head 통합 — lotteon_order_dedup_fix + orderer_name.

기존 main에서 zzzzzzz_drop_is_unregistered.down_revision이 dd3eaff7233e(프로덕션 HEAD)로
재지정되며 zzzzzz_lotteon_order_dedup_fix가 dangling head로 남아 있었음.
본 PR의 zzzzzzzzzzz_add_orderer_name_to_samba_order까지 head가 2개가 되어
CI Check single head를 통과하지 못함 → 빈 머지 리비전으로 통합.

Revision ID: zzzzzzzzzzzz_merge_heads_lotteon_dedup_orderer_name
Revises: zzzzzz_lotteon_order_dedup_fix, zzzzzzzzzzz_add_orderer_name_to_samba_order
Create Date: 2026-05-09
"""

revision = "zzzzzzzzzzzz_merge_heads_lotteon_dedup_orderer_name"
down_revision = (
    "zzzzzz_lotteon_order_dedup_fix",
    "zzzzzzzzzzz_add_orderer_name_to_samba_order",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
