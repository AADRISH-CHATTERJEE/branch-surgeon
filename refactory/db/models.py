"""SQLAlchemy ORM models for the Refactory persistence layer.

These are *persistence* models — separate from the Pydantic business models
in refactory/review/models.py, refactory/recommendation/models.py, etc.
Mapping between ORM and business models is the repository's responsibility.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from refactory.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class RepositoryModel(Base):
    __tablename__ = "db_repositories"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    root_path = Column(Text, nullable=False, unique=True)
    default_branch = Column(String(100), default="main")
    remote_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    files = relationship("FileModel", back_populates="repository", cascade="all, delete-orphan")
    reviews = relationship("ReviewModel", back_populates="repository", cascade="all, delete-orphan")
    recommendations = relationship(
        "RecommendationModel", back_populates="repository", cascade="all, delete-orphan"
    )
    graph_nodes = relationship("GraphNodeModel", back_populates="repository", cascade="all, delete-orphan")
    metrics = relationship("MetricModel", back_populates="repository", cascade="all, delete-orphan")
    analysis_runs = relationship("AnalysisRunModel", back_populates="repository", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_db_repo_name", "name"),
        Index("ix_db_repo_root_path", "root_path"),
    )


# ---------------------------------------------------------------------------
# File
# ---------------------------------------------------------------------------

class FileModel(Base):
    __tablename__ = "db_files"

    id = Column(String(36), primary_key=True, default=_uuid)
    repository_id = Column(String(36), ForeignKey("db_repositories.id", ondelete="CASCADE"), nullable=False)
    path = Column(Text, nullable=False)
    language = Column(String(50), default="unknown")
    sha256 = Column(String(64), nullable=True)
    size = Column(Integer, default=0)
    last_indexed = Column(DateTime(timezone=True), nullable=True)

    repository = relationship("RepositoryModel", back_populates="files")
    symbols = relationship("SymbolModel", back_populates="file", cascade="all, delete-orphan")
    imports = relationship("ImportModel", back_populates="file", cascade="all, delete-orphan")
    embeddings = relationship("EmbeddingModel", back_populates="file", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_db_file_repo_path", "repository_id", "path", unique=True),
        Index("ix_db_file_language", "language"),
    )


# ---------------------------------------------------------------------------
# Symbol
# ---------------------------------------------------------------------------

class SymbolModel(Base):
    __tablename__ = "db_symbols"

    id = Column(String(36), primary_key=True, default=_uuid)
    file_id = Column(String(36), ForeignKey("db_files.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)
    line = Column(Integer, nullable=True)
    column = Column(Integer, nullable=True)
    signature = Column(Text, nullable=True)

    file = relationship("FileModel", back_populates="symbols")

    __table_args__ = (
        Index("ix_db_symbol_file", "file_id"),
        Index("ix_db_symbol_name", "name"),
        Index("ix_db_symbol_type", "type"),
    )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

class ImportModel(Base):
    __tablename__ = "db_imports"

    id = Column(String(36), primary_key=True, default=_uuid)
    file_id = Column(String(36), ForeignKey("db_files.id", ondelete="CASCADE"), nullable=False)
    module = Column(String(255), nullable=False)
    symbol = Column(String(255), nullable=True)

    file = relationship("FileModel", back_populates="imports")

    __table_args__ = (
        Index("ix_db_import_file", "file_id"),
        Index("ix_db_import_module", "module"),
    )


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

class ReviewModel(Base):
    __tablename__ = "db_reviews"

    id = Column(String(36), primary_key=True, default=_uuid)
    repository_id = Column(String(36), ForeignKey("db_repositories.id", ondelete="CASCADE"), nullable=False)
    pr_number = Column(Integer, nullable=True)
    provider = Column(String(50), nullable=True)
    model = Column(String(100), nullable=True)
    risk = Column(String(20), default="unknown")
    confidence = Column(Float, default=0.0)
    summary = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    repository = relationship("RepositoryModel", back_populates="reviews")
    suggestions = relationship(
        "ReviewSuggestionModel", back_populates="review", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_db_review_repo", "repository_id"),
        Index("ix_db_review_pr", "pr_number"),
        Index("ix_db_review_created", "created_at"),
    )


# ---------------------------------------------------------------------------
# ReviewSuggestion
# ---------------------------------------------------------------------------

class ReviewSuggestionModel(Base):
    __tablename__ = "db_review_suggestions"

    id = Column(String(36), primary_key=True, default=_uuid)
    review_id = Column(String(36), ForeignKey("db_reviews.id", ondelete="CASCADE"), nullable=False)
    file = Column(Text, nullable=True)
    line = Column(Integer, nullable=True)
    severity = Column(String(20), default="info")
    category = Column(String(100), nullable=True)
    title = Column(String(500), default="")
    explanation = Column(Text, default="")
    suggested_fix = Column(Text, default="")
    confidence = Column(Float, nullable=True)
    estimated_impact = Column(Text, default="")
    status = Column(String(20), default="pending")
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    ignored_at = Column(DateTime(timezone=True), nullable=True)
    updated_by = Column(String(100), nullable=True)
    recommendation_id = Column(String(36), nullable=True)

    review = relationship("ReviewModel", back_populates="suggestions")

    __table_args__ = (
        Index("ix_db_suggestion_review", "review_id"),
        Index("ix_db_suggestion_severity", "severity"),
        Index("ix_db_suggestion_status", "status"),
    )


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------

class RecommendationModel(Base):
    __tablename__ = "db_recommendations"

    id = Column(String(36), primary_key=True, default=_uuid)
    repository_id = Column(String(36), ForeignKey("db_repositories.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(100), nullable=False)
    priority = Column(String(20), default="medium")
    status = Column(String(20), default="pending")
    title = Column(String(500), nullable=False)
    description = Column(Text, default="")
    reasoning = Column(Text, default="")
    affected_files = Column(JSON, nullable=True)
    impact = Column(JSON, nullable=True)  # list[str] tags
    effort = Column(String(10), default="")  # XS | S | M | L | XL
    confidence = Column(Float, nullable=True)
    resolution_notes = Column(Text, default="")
    verification_status = Column(String(40), default="unverified")
    patch_history = Column(JSON, nullable=True)  # denormalized summary; patches table is source of truth
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    ignored_at = Column(DateTime(timezone=True), nullable=True)
    updated_by = Column(String(100), nullable=True)

    repository = relationship("RepositoryModel", back_populates="recommendations")
    patches = relationship(
        "PatchModel", back_populates="recommendation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_db_rec_repo", "repository_id"),
        Index("ix_db_rec_type", "type"),
        Index("ix_db_rec_priority", "priority"),
        Index("ix_db_rec_status", "status"),
    )


# ---------------------------------------------------------------------------
# Generated patch (recommendation → AI patch)
# ---------------------------------------------------------------------------

class PatchModel(Base):
    """Persisted AI-generated patch linked to a recommendation + repository."""

    __tablename__ = "db_patches"

    id = Column(String(36), primary_key=True, default=_uuid)
    recommendation_id = Column(
        String(36), ForeignKey("db_recommendations.id", ondelete="CASCADE"), nullable=False
    )
    repository_id = Column(
        String(36), ForeignKey("db_repositories.id", ondelete="CASCADE"), nullable=False
    )
    explanation = Column(Text, default="")
    confidence = Column(Float, default=0.0)
    changed_files = Column(JSON, nullable=True)
    unified_diff = Column(Text, default="")
    patches = Column(JSON, nullable=True)
    prompt_version = Column(String(50), default="")
    model = Column(String(100), default="")
    provider = Column(String(100), default="")
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    # Apply lifecycle (Phase apply-patch completion)
    status = Column(String(30), default="generated")
    applied_at = Column(DateTime(timezone=True), nullable=True)
    applied_by = Column(String(100), nullable=True)
    git_commit = Column(String(40), nullable=True)
    failure_reason = Column(Text, nullable=True)
    rollback_metadata = Column(JSON, nullable=True)

    recommendation = relationship("RecommendationModel", back_populates="patches")
    repository = relationship("RepositoryModel")

    __table_args__ = (
        Index("ix_db_patch_rec", "recommendation_id"),
        Index("ix_db_patch_repo", "repository_id"),
        Index("ix_db_patch_created", "created_at"),
        Index("ix_db_patch_status", "status"),
    )


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

class EmbeddingModel(Base):
    __tablename__ = "db_embeddings"

    id = Column(String(36), primary_key=True, default=_uuid)
    file_id = Column(String(36), ForeignKey("db_files.id", ondelete="CASCADE"), nullable=False)
    chunk_id = Column(String(100), nullable=False)
    provider = Column(String(100), default="")
    model = Column(String(100), default="")
    vector_reference = Column(Text, default="")

    file = relationship("FileModel", back_populates="embeddings")

    __table_args__ = (
        Index("ix_db_emb_file", "file_id"),
        Index("ix_db_emb_chunk", "chunk_id"),
    )


# ---------------------------------------------------------------------------
# GraphNode
# ---------------------------------------------------------------------------

class GraphNodeModel(Base):
    __tablename__ = "db_graph_nodes"

    id = Column(String(36), primary_key=True, default=_uuid)
    repository_id = Column(String(36), ForeignKey("db_repositories.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)

    repository = relationship("RepositoryModel", back_populates="graph_nodes")
    outgoing_edges = relationship(
        "GraphEdgeModel",
        foreign_keys="GraphEdgeModel.source_node",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    incoming_edges = relationship(
        "GraphEdgeModel",
        foreign_keys="GraphEdgeModel.target_node",
        back_populates="target",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_db_gnode_repo", "repository_id"),
        Index("ix_db_gnode_name", "name"),
        Index("ix_db_gnode_type", "type"),
    )


# ---------------------------------------------------------------------------
# GraphEdge
# ---------------------------------------------------------------------------

class GraphEdgeModel(Base):
    __tablename__ = "db_graph_edges"

    id = Column(String(36), primary_key=True, default=_uuid)
    source_node = Column(String(36), ForeignKey("db_graph_nodes.id", ondelete="CASCADE"), nullable=False)
    target_node = Column(String(36), ForeignKey("db_graph_nodes.id", ondelete="CASCADE"), nullable=False)
    relationship_ = Column("relationship", String(100), nullable=False)

    source = relationship("GraphNodeModel", foreign_keys=[source_node], back_populates="outgoing_edges")
    target = relationship("GraphNodeModel", foreign_keys=[target_node], back_populates="incoming_edges")

    __table_args__ = (
        Index("ix_db_gedge_source", "source_node"),
        Index("ix_db_gedge_target", "target_node"),
        Index("ix_db_gedge_rel", "relationship"),
    )


# ---------------------------------------------------------------------------
# HistoricalMetric
# ---------------------------------------------------------------------------

class MetricModel(Base):
    __tablename__ = "db_metrics"

    id = Column(String(36), primary_key=True, default=_uuid)
    repository_id = Column(String(36), ForeignKey("db_repositories.id", ondelete="CASCADE"), nullable=False)
    metric_name = Column(String(100), nullable=False)
    metric_value = Column(Float, nullable=False)
    git_commit = Column(String(40), nullable=True)
    branch = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    metadata_ = Column("metadata", JSON, nullable=True)

    repository = relationship("RepositoryModel", back_populates="metrics")

    __table_args__ = (
        Index("ix_db_metric_repo_name_time", "repository_id", "metric_name", "created_at"),
        Index("ix_db_metric_name", "metric_name"),
    )


# ---------------------------------------------------------------------------
# Organization rules (company policies)
# ---------------------------------------------------------------------------

class OrganizationRuleModel(Base):
    """Configurable organization / company policy rules (additive to built-ins)."""

    __tablename__ = "organization_rules"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    category = Column(String(100), default="custom")
    severity = Column(String(20), default="warning")
    enabled = Column(Boolean, default=True, nullable=False)
    rule_type = Column(String(50), default="custom")
    conditions = Column(JSON, nullable=True)
    condition_logic = Column(String(10), default="and")
    message = Column(Text, default="")
    documentation_url = Column(String(500), default="")
    blocking = Column(Boolean, default=False, nullable=False)
    # Phase 11.5 — scope (NULL team_id = org-global rule)
    organization_id = Column(String(36), nullable=True)
    team_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_org_rules_name", "name"),
        Index("ix_org_rules_enabled", "enabled"),
        Index("ix_org_rules_type", "rule_type"),
        Index("ix_org_rules_severity", "severity"),
        Index("ix_org_rules_org", "organization_id"),
        Index("ix_org_rules_team", "team_id"),
    )


# ---------------------------------------------------------------------------
# Organization management (Phase 11.5) — local multi-tenant catalog
# ---------------------------------------------------------------------------


class OrganizationModel(Base):
    __tablename__ = "organizations"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True)
    description = Column(Text, default="")
    branding = Column(JSON, nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    teams = relationship(
        "TeamModel", back_populates="organization", cascade="all, delete-orphan"
    )
    members = relationship(
        "OrganizationMemberModel",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    repositories = relationship(
        "OrganizationRepositoryModel",
        back_populates="organization",
        cascade="all, delete-orphan",
    )


class TeamModel(Base):
    __tablename__ = "teams"

    id = Column(String(36), primary_key=True, default=_uuid)
    organization_id = Column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    organization = relationship("OrganizationModel", back_populates="teams")
    members = relationship(
        "TeamMemberModel", back_populates="team", cascade="all, delete-orphan"
    )
    repositories = relationship(
        "TeamRepositoryModel", back_populates="team", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_teams_org", "organization_id"),
        Index("ix_teams_org_slug", "organization_id", "slug", unique=True),
    )


class OrganizationMemberModel(Base):
    """Local member profile — no login / SSO (Enterprise later)."""

    __tablename__ = "organization_members"

    id = Column(String(36), primary_key=True, default=_uuid)
    organization_id = Column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    display_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    role = Column(String(30), default="developer", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    organization = relationship("OrganizationModel", back_populates="members")
    team_memberships = relationship(
        "TeamMemberModel", back_populates="member", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_org_members_org", "organization_id"),
        Index("ix_org_members_email", "email"),
    )


class TeamMemberModel(Base):
    __tablename__ = "team_members"

    id = Column(String(36), primary_key=True, default=_uuid)
    team_id = Column(
        String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    member_id = Column(
        String(36),
        ForeignKey("organization_members.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(30), default="member", nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    team = relationship("TeamModel", back_populates="members")
    member = relationship("OrganizationMemberModel", back_populates="team_memberships")

    __table_args__ = (
        Index("ix_team_members_team", "team_id"),
        Index("ix_team_members_unique", "team_id", "member_id", unique=True),
    )


class OrganizationRepositoryModel(Base):
    """Links a filesystem git root to an organization."""

    __tablename__ = "organization_repositories"

    id = Column(String(36), primary_key=True, default=_uuid)
    organization_id = Column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    repository_root_path = Column(Text, nullable=False)
    repository_name = Column(String(255), default="")
    nickname = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    organization = relationship("OrganizationModel", back_populates="repositories")
    team_links = relationship(
        "TeamRepositoryModel",
        back_populates="organization_repository",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_org_repos_org", "organization_id"),
        Index(
            "ix_org_repos_unique",
            "organization_id",
            "repository_root_path",
            unique=True,
        ),
    )


class TeamRepositoryModel(Base):
    __tablename__ = "team_repositories"

    id = Column(String(36), primary_key=True, default=_uuid)
    team_id = Column(
        String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    organization_repository_id = Column(
        String(36),
        ForeignKey("organization_repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    team = relationship("TeamModel", back_populates="repositories")
    organization_repository = relationship(
        "OrganizationRepositoryModel", back_populates="team_links"
    )

    __table_args__ = (
        Index("ix_team_repos_team", "team_id"),
        Index(
            "ix_team_repos_unique",
            "team_id",
            "organization_repository_id",
            unique=True,
        ),
    )


class OrganizationRuleAuditModel(Base):
    """Audit trail for organization rule create/edit/enable/disable/delete."""

    __tablename__ = "organization_rule_audits"

    id = Column(String(36), primary_key=True, default=_uuid)
    rule_id = Column(String(36), nullable=False)
    action = Column(String(50), nullable=False)
    actor = Column(String(100), default="local")
    changes = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_org_rule_audit_rule", "rule_id"),
        Index("ix_org_rule_audit_created", "created_at"),
    )


# ---------------------------------------------------------------------------
# Analysis History (Phase 11.3 — historical memory of analysis results)
# ---------------------------------------------------------------------------

class AnalysisHistoryModel(Base):
    """First-class history of completed analyses (complements Activity runs)."""

    __tablename__ = "analysis_history"

    id = Column(String(36), primary_key=True, default=_uuid)
    timestamp = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    analysis_type = Column(String(50), nullable=False)
    repository_id = Column(
        String(36), ForeignKey("db_repositories.id", ondelete="CASCADE"), nullable=False
    )
    repository_name = Column(String(255), default="")
    branch = Column(String(100), nullable=True)
    commit = Column(String(40), nullable=True)
    status = Column(String(20), default="completed")
    duration_ms = Column(Float, default=0.0)
    summary = Column(Text, default="")
    created_by = Column(String(100), default="local")
    metadata_ = Column("metadata", JSON, nullable=True)
    # Result payload for drawer / export (inputs, outputs, warnings, links)
    result_data = Column(JSON, nullable=True)
    # Optional link back to Activity analysis run
    analysis_run_id = Column(String(36), nullable=True)
    # Phase 11.5 — optional org / actor context
    organization_id = Column(String(36), nullable=True)
    created_by_user = Column(String(100), nullable=True)

    __table_args__ = (
        Index("ix_analysis_history_repo_time", "repository_id", "timestamp"),
        Index("ix_analysis_history_type", "analysis_type"),
        Index("ix_analysis_history_status", "status"),
        Index("ix_analysis_history_branch", "branch"),
        Index("ix_analysis_history_org", "organization_id"),
    )


# ---------------------------------------------------------------------------
# AnalysisRun
# ---------------------------------------------------------------------------

class AnalysisRunModel(Base):
    __tablename__ = "db_analysis_runs"

    id = Column(String(36), primary_key=True, default=_uuid)
    repository_id = Column(String(36), ForeignKey("db_repositories.id", ondelete="CASCADE"), nullable=False)
    command = Column(String(100), nullable=False)
    status = Column(String(20), default="completed")
    git_commit = Column(String(40), nullable=True)
    branch = Column(String(100), nullable=True)
    duration_ms = Column(Float, default=0.0)
    result_type = Column(String(50), nullable=False)
    result_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    metadata_ = Column("metadata", JSON, nullable=True)

    repository = relationship("RepositoryModel", back_populates="analysis_runs")

    __table_args__ = (
        Index("ix_db_run_repo_time", "repository_id", "created_at"),
        Index("ix_db_run_command", "command"),
        Index("ix_db_run_status", "status"),
        Index("ix_db_run_commit", "git_commit"),
    )
