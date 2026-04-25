"""add customer_note to samba_order

Revision ID: 202604251130_add_customer_note
Revises: 202604232300_dedup_default_true
Create Date: 2026-04-25 11:30:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "202604251130_add_customer_note"
down_revision: Union[str, Sequence[str], None] = "202604232300_dedup_default_true"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE samba_order ADD COLUMN IF NOT EXISTS customer_note TEXT")
    op.execute(
        """
        UPDATE samba_order
        SET customer_note = notes
        WHERE customer_note IS NULL
          AND COALESCE(notes, '') <> ''
          AND source IN ('lotteon', 'ssg')
        """
    )


def downgrade() -> None:
    op.drop_column("samba_order", "customer_note")
