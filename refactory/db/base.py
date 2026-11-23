"""Declarative base for all ORM models in the db layer."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass


class Base(DeclarativeBase):
    """Base class for all Refactory ORM models.

    Uses SQLAlchemy 2.0 DeclarativeBase. All ORM models in refactory/db/models.py
    inherit from this base. This is intentionally separate from
    refactory/storage/models.Base to avoid table conflicts.
    """

    pass
