from sqlalchemy.ext.asyncio import AsyncSession


class RawQueryRepository:
    """Repository for executing raw SQL queries."""

    def __init__(self, session: AsyncSession):
        self.session = session
