"""Add review suggestion lifecycle columns (created_at + status fields).

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {
        row[1] for row in conn.execute(sa.text("PRAGMA table_info(db_review_suggestions)"))
    }
    columns = [
        ("status", sa.Column("status", sa.String(20), server_default="pending")),
        ("created_at", sa.Column("created_at", sa.DateTime(timezone=True))),
        ("updated_at", sa.Column("updated_at", sa.DateTime(timezone=True))),
        ("resolved_at", sa.Column("resolved_at", sa.DateTime(timezone=True))),
        ("ignored_at", sa.Column("ignored_at", sa.DateTime(timezone=True))),
        ("updated_by", sa.Column("updated_by", sa.String(100))),
        ("recommendation_id", sa.Column("recommendation_id", sa.String(36))),
    ]
    for name, column in columns:
        if name not in existing:
            op.add_column("db_review_suggestions", column)
    # Index may already exist from ensure_schema / create_all.
    try:
        op.create_index(
            "ix_db_suggestion_status", "db_review_suggestions", ["status"]
        )
    except Exception:  # noqa: BLE001
        pass


def downgrade() -> None:
    try:
        op.drop_index("ix_db_suggestion_status", table_name="db_review_suggestions")
    except Exception:  # noqa: BLE001
        pass
    for name in (
        "recommendation_id",
        "updated_by",
        "ignored_at",
        "resolved_at",
        "updated_at",
        "created_at",
        "status",
    ):
        try:
            op.drop_column("db_review_suggestions", name)
        except Exception:  # noqa: BLE001
            pass
