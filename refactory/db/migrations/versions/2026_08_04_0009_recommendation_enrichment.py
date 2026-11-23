"""Enrich db_recommendations with reasoning / lifecycle metadata.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {
        row[1] for row in conn.execute(sa.text("PRAGMA table_info(db_recommendations)"))
    }
    columns = [
        ("reasoning", sa.Column("reasoning", sa.Text(), server_default="")),
        ("affected_files", sa.Column("affected_files", sa.JSON())),
        ("impact", sa.Column("impact", sa.JSON())),
        ("effort", sa.Column("effort", sa.String(10), server_default="")),
        ("confidence", sa.Column("confidence", sa.Float())),
        ("resolution_notes", sa.Column("resolution_notes", sa.Text(), server_default="")),
        (
            "verification_status",
            sa.Column("verification_status", sa.String(40), server_default="unverified"),
        ),
        ("patch_history", sa.Column("patch_history", sa.JSON())),
        ("updated_at", sa.Column("updated_at", sa.DateTime(timezone=True))),
        ("resolved_at", sa.Column("resolved_at", sa.DateTime(timezone=True))),
        ("ignored_at", sa.Column("ignored_at", sa.DateTime(timezone=True))),
        ("updated_by", sa.Column("updated_by", sa.String(100))),
    ]
    for name, column in columns:
        if name not in existing:
            op.add_column("db_recommendations", column)


def downgrade() -> None:
    for name in (
        "updated_by",
        "ignored_at",
        "resolved_at",
        "updated_at",
        "patch_history",
        "verification_status",
        "resolution_notes",
        "confidence",
        "effort",
        "impact",
        "affected_files",
        "reasoning",
    ):
        try:
            op.drop_column("db_recommendations", name)
        except Exception:  # noqa: BLE001
            pass
