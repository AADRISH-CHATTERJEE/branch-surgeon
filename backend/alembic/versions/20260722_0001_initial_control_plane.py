"""Initial control plane tables (users, telemetry).

Revision ID: 20260722_0001
Revises:
Create Date: 2026-07-22

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "telemetry_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("cli_version", sa.String(length=50), nullable=True),
        sa.Column("os_name", sa.String(length=50), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_telemetry_events_user_id", "telemetry_events", ["user_id"], unique=False)
    op.create_index("ix_telemetry_events_event_type", "telemetry_events", ["event_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_telemetry_events_event_type", table_name="telemetry_events")
    op.drop_index("ix_telemetry_events_user_id", table_name="telemetry_events")
    op.drop_table("telemetry_events")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
