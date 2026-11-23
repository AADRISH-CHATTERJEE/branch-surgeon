"""Database persistence layer for Refactory.

Provides SQLAlchemy 2.0 ORM models, repository pattern, Unit of Work,
and Alembic-managed migrations. SQLite (default) and PostgreSQL compatible.
"""

from refactory.db.base import Base
from refactory.db.database import DatabaseManager
from refactory.db.session import SessionFactory, get_session_factory
from refactory.db.uow import UnitOfWork

__all__ = [
    "Base",
    "DatabaseManager",
    "SessionFactory",
    "UnitOfWork",
    "get_session_factory",
]
