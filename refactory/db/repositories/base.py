"""Base repository with shared CRUD logic."""

from __future__ import annotations

from typing import Generic, Sequence, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from refactory.db.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """Generic repository providing standard CRUD operations.

    Subclasses set ``model_class`` to their ORM model.
    """

    model_class: type[T]

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **kwargs) -> T:
        """Create and persist a new entity."""
        instance = self.model_class(**kwargs)
        self._session.add(instance)
        self._session.flush()
        return instance

    def get_by_id(self, entity_id: str) -> T | None:
        """Retrieve a single entity by primary key."""
        return self._session.get(self.model_class, entity_id)

    def get(self, **filters) -> T | None:
        """Retrieve the first entity matching the given filters."""
        stmt = select(self.model_class).filter_by(**filters)
        return self._session.execute(stmt).scalar_one_or_none()

    def list(self, *, limit: int = 100, offset: int = 0, **filters) -> Sequence[T]:
        """List entities with optional filters and pagination."""
        stmt = select(self.model_class).filter_by(**filters).limit(limit).offset(offset)
        return self._session.execute(stmt).scalars().all()

    def update(self, entity_id: str, **values) -> T | None:
        """Update an entity by primary key. Returns the updated entity or None."""
        instance = self.get_by_id(entity_id)
        if instance is None:
            return None
        for key, value in values.items():
            setattr(instance, key, value)
        self._session.flush()
        return instance

    def delete(self, entity_id: str) -> bool:
        """Delete an entity by primary key. Returns True if deleted."""
        instance = self.get_by_id(entity_id)
        if instance is None:
            return False
        self._session.delete(instance)
        self._session.flush()
        return True

    def bulk_insert(self, entities: list[dict]) -> list[T]:
        """Bulk-insert entities from dicts. Returns created instances."""
        instances = [self.model_class(**data) for data in entities]
        self._session.add_all(instances)
        self._session.flush()
        return instances

    def exists(self, **filters) -> bool:
        """Check if an entity matching the filters exists."""
        return self.get(**filters) is not None

    def count(self, **filters) -> int:
        """Count entities matching the given filters."""
        from sqlalchemy import func

        stmt = select(func.count()).select_from(self.model_class).filter_by(**filters)
        result = self._session.execute(stmt).scalar()
        return result or 0
