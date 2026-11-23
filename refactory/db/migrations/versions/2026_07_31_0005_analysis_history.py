"""Add analysis_history table for Phase 11.3 historical memory.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analysis_type", sa.String(50), nullable=False),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("db_repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("repository_name", sa.String(255), server_default=""),
        sa.Column("branch", sa.String(100), nullable=True),
        sa.Column("commit", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), server_default="completed"),
        sa.Column("duration_ms", sa.Float, server_default="0"),
        sa.Column("summary", sa.Text, server_default=""),
        sa.Column("created_by", sa.String(100), server_default="local"),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("result_data", sa.JSON, nullable=True),
        sa.Column("analysis_run_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_analysis_history_repo_time",
        "analysis_history",
        ["repository_id", "timestamp"],
    )
    op.create_index("ix_analysis_history_type", "analysis_history", ["analysis_type"])
    op.create_index("ix_analysis_history_status", "analysis_history", ["status"])
    op.create_index("ix_analysis_history_branch", "analysis_history", ["branch"])


def downgrade() -> None:
    op.drop_index("ix_analysis_history_branch", table_name="analysis_history")
    op.drop_index("ix_analysis_history_status", table_name="analysis_history")
    op.drop_index("ix_analysis_history_type", table_name="analysis_history")
    op.drop_index("ix_analysis_history_repo_time", table_name="analysis_history")
    op.drop_table("analysis_history")
