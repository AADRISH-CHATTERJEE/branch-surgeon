"""Add patch apply lifecycle columns.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "db_patches",
        sa.Column("status", sa.String(30), server_default="generated"),
    )
    op.add_column("db_patches", sa.Column("applied_at", sa.DateTime(timezone=True)))
    op.add_column("db_patches", sa.Column("applied_by", sa.String(100)))
    op.add_column("db_patches", sa.Column("git_commit", sa.String(40)))
    op.add_column("db_patches", sa.Column("failure_reason", sa.Text()))
    op.add_column("db_patches", sa.Column("rollback_metadata", sa.JSON()))
    op.create_index("ix_db_patch_status", "db_patches", ["status"])


def downgrade() -> None:
    op.drop_index("ix_db_patch_status", table_name="db_patches")
    op.drop_column("db_patches", "rollback_metadata")
    op.drop_column("db_patches", "failure_reason")
    op.drop_column("db_patches", "git_commit")
    op.drop_column("db_patches", "applied_by")
    op.drop_column("db_patches", "applied_at")
    op.drop_column("db_patches", "status")
