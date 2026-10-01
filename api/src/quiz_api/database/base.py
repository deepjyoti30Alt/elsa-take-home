"""SQLAlchemy declarative base for durable quiz state."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class that owns the application's SQLAlchemy metadata."""
