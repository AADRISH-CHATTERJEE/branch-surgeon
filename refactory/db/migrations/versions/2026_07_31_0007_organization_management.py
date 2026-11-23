"""Phase 11.5 — Organization management tables + rule/history scoping.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("branding", sa.JSON(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_teams_org", "teams", ["organization_id"])
    op.create_index("ix_teams_org_slug", "teams", ["organization_id", "slug"], unique=True)

    op.create_table(
        "organization_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("role", sa.String(30), server_default="developer", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_org_members_org", "organization_members", ["organization_id"])

    op.create_table(
        "team_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "team_id",
            sa.String(36),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            sa.String(36),
            sa.ForeignKey("organization_members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(30), server_default="member", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_team_members_unique", "team_members", ["team_id", "member_id"], unique=True
    )

    op.create_table(
        "organization_repositories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("repository_root_path", sa.Text(), nullable=False),
        sa.Column("repository_name", sa.String(255), server_default=""),
        sa.Column("nickname", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_org_repos_unique",
        "organization_repositories",
        ["organization_id", "repository_root_path"],
        unique=True,
    )

    op.create_table(
        "team_repositories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "team_id",
            sa.String(36),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_repository_id",
            sa.String(36),
            sa.ForeignKey("organization_repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_team_repos_unique",
        "team_repositories",
        ["team_id", "organization_repository_id"],
        unique=True,
    )

    op.add_column("organization_rules", sa.Column("organization_id", sa.String(36)))
    op.add_column("organization_rules", sa.Column("team_id", sa.String(36)))
    op.create_index("ix_org_rules_org", "organization_rules", ["organization_id"])
    op.create_index("ix_org_rules_team", "organization_rules", ["team_id"])

    op.add_column("analysis_history", sa.Column("organization_id", sa.String(36)))
    op.add_column("analysis_history", sa.Column("created_by_user", sa.String(100)))
    op.create_index("ix_analysis_history_org", "analysis_history", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_history_org", table_name="analysis_history")
    op.drop_column("analysis_history", "created_by_user")
    op.drop_column("analysis_history", "organization_id")
    op.drop_index("ix_org_rules_team", table_name="organization_rules")
    op.drop_index("ix_org_rules_org", table_name="organization_rules")
    op.drop_column("organization_rules", "team_id")
    op.drop_column("organization_rules", "organization_id")
    op.drop_table("team_repositories")
    op.drop_table("organization_repositories")
    op.drop_table("team_members")
    op.drop_table("organization_members")
    op.drop_table("teams")
    op.drop_table("organizations")
