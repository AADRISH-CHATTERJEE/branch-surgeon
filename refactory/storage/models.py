"""SQLAlchemy ORM models for persistent storage."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class RepositoryRecord(Base):
    __tablename__ = "repositories"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    path = Column(Text, nullable=False)
    remote_url = Column(Text, nullable=True)
    default_branch = Column(String(100), default="main")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    is_active = Column(Boolean, default=True)
    metadata_ = Column("metadata", JSON, default=dict)

    analyses = relationship("AnalysisRun", back_populates="repository", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_repositories_name", "name"),
        Index("ix_repositories_path", "path"),
    )


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id = Column(String(36), primary_key=True, default=_uuid)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=False)
    command = Column(String(100), nullable=False)
    status = Column(String(20), default="completed")
    git_commit = Column(String(40), nullable=True)
    branch = Column(String(100), nullable=True)
    timestamp = Column(DateTime(timezone=True), default=_utcnow)
    duration_ms = Column(Float, default=0.0)
    result_type = Column(String(50), nullable=False)
    result_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)

    repository = relationship("RepositoryRecord", back_populates="analyses")

    __table_args__ = (
        Index("ix_analysis_runs_repo_time", "repository_id", "timestamp"),
        Index("ix_analysis_runs_command", "command"),
        Index("ix_analysis_runs_status", "status"),
        Index("ix_analysis_runs_commit", "git_commit"),
    )


class HistoricalMetric(Base):
    __tablename__ = "historical_metrics"

    id = Column(String(36), primary_key=True, default=_uuid)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=False)
    metric_name = Column(String(100), nullable=False)
    metric_value = Column(Float, nullable=False)
    git_commit = Column(String(40), nullable=True)
    branch = Column(String(100), nullable=True)
    timestamp = Column(DateTime(timezone=True), default=_utcnow)
    metadata_ = Column("metadata", JSON, default=dict)

    __table_args__ = (
        Index("ix_metrics_repo_name_time", "repository_id", "metric_name", "timestamp"),
    )


class RuleRecord(Base):
    __tablename__ = "rules"

    id = Column(String(36), primary_key=True, default=_uuid)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    category = Column(String(50), nullable=False)
    severity = Column(String(20), default="warning")
    enabled = Column(Boolean, default=True)
    blocking = Column(Boolean, default=False)
    conditions = Column(JSON, default=dict)
    message = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_rules_repo_category", "repository_id", "category"),
    )


class SessionRecord(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=_uuid)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=True)
    started_at = Column(DateTime(timezone=True), default=_utcnow)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    commands_run = Column(Integer, default=0)
    metadata_ = Column("metadata", JSON, default=dict)
