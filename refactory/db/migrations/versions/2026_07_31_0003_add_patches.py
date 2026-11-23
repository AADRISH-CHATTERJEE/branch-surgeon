"""Add db_patches table for AI recommendation patches.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "db_patches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "recommendation_id",
            sa.String(36),
            sa.ForeignKey("db_recommendations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("db_repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("explanation", sa.Text, server_default=""),
        sa.Column("confidence", sa.Float, server_default="0"),
        sa.Column("changed_files", sa.JSON, nullable=True),
        sa.Column("unified_diff", sa.Text, server_default=""),
        sa.Column("patches", sa.JSON, nullable=True),
        sa.Column("prompt_version", sa.String(50), server_default=""),
        sa.Column("model", sa.String(100), server_default=""),
        sa.Column("provider", sa.String(100), server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_db_patch_rec", "db_patches", ["recommendation_id"])
    op.create_index("ix_db_patch_repo", "db_patches", ["repository_id"])
    op.create_index("ix_db_patch_created", "db_patches", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_db_patch_created", table_name="db_patches")
    op.drop_index("ix_db_patch_repo", table_name="db_patches")
    op.drop_index("ix_db_patch_rec", table_name="db_patches")
    op.drop_table("db_patches")
