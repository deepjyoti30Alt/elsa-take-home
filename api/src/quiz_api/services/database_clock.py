"""Database-backed wall-clock access shared by time-sensitive services."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_database_clock(session: AsyncSession) -> datetime:
    """Read PostgreSQL's wall clock so all API instances use one timeline."""
    database_time: object = (await session.execute(select(func.clock_timestamp()))).scalar_one()
    if not isinstance(database_time, datetime):
        message = "Database did not return a timestamp."
        raise RuntimeError(message)
    return database_time
