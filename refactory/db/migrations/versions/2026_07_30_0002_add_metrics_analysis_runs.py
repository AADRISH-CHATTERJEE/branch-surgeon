"""Add metrics and analysis_runs tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- HistoricalMetric ---
    op.create_table(
        "db_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("db_repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("metric_value", sa.Float, nullable=False),
        sa.Column("git_commit", sa.String(40), nullable=True),
        sa.Column("branch", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON, nullable=True),
    )
    op.create_index(
        "ix_db_metric_repo_name_time",
        "db_metrics",
        ["repository_id", "metric_name", "created_at"],
    )
    op.create_index("ix_db_metric_name", "db_metrics", ["metric_name"])

    # --- AnalysisRun ---
    op.create_table(
        "db_analysis_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("db_repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("command", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), server_default="completed"),
        sa.Column("git_commit", sa.String(40), nullable=True),
        sa.Column("branch", sa.String(100), nullable=True),
        sa.Column("duration_ms", sa.Float, server_default="0.0"),
        sa.Column("result_type", sa.String(50), nullable=False),
        sa.Column("result_data", sa.JSON, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON, nullable=True),
    )
    op.create_index(
        "ix_db_run_repo_time", "db_analysis_runs", ["repository_id", "created_at"]
    )
    op.create_index("ix_db_run_command", "db_analysis_runs", ["command"])
    op.create_index("ix_db_run_status", "db_analysis_runs", ["status"])
    op.create_index("ix_db_run_commit", "db_analysis_runs", ["git_commit"])


def downgrade() -> None:
    op.drop_table("db_analysis_runs")
    op.drop_table("db_metrics")
