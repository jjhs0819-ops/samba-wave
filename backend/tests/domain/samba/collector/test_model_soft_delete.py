"""Test soft delete (deleted_at) column on SambaCollectedProduct model."""

import pytest
from sqlalchemy import inspect

from backend.domain.samba.collector.model import SambaCollectedProduct


def test_collected_product_has_deleted_at_column():
    """Verify that SambaCollectedProduct model has a deleted_at column."""
    columns = {c.name for c in inspect(SambaCollectedProduct).columns}
    assert "deleted_at" in columns


@pytest.mark.asyncio
async def test_new_product_deleted_at_defaults_to_none(db_session):
    """Verify that a new product's deleted_at defaults to None."""
    p = SambaCollectedProduct(source_site="TEST", name="테스트상품")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    assert p.deleted_at is None
