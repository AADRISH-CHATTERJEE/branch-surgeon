"""Add organization_rules and organization_rule_audits tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("category", sa.String(100), server_default="custom"),
        sa.Column("severity", sa.String(20), server_default="warning"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("rule_type", sa.String(50), server_default="custom"),
        sa.Column("conditions", sa.JSON, nullable=True),
        sa.Column("condition_logic", sa.String(10), server_default="and"),
        sa.Column("message", sa.Text, server_default=""),
        sa.Column("documentation_url", sa.String(500), server_default=""),
        sa.Column("blocking", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_org_rules_name", "organization_rules", ["name"])
    op.create_index("ix_org_rules_enabled", "organization_rules", ["enabled"])
    op.create_index("ix_org_rules_type", "organization_rules", ["rule_type"])
    op.create_index("ix_org_rules_severity", "organization_rules", ["severity"])

    op.create_table(
        "organization_rule_audits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rule_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("actor", sa.String(100), server_default="local"),
        sa.Column("changes", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_org_rule_audit_rule", "organization_rule_audits", ["rule_id"])
    op.create_index(
        "ix_org_rule_audit_created", "organization_rule_audits", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_org_rule_audit_created", table_name="organization_rule_audits")
    op.drop_index("ix_org_rule_audit_rule", table_name="organization_rule_audits")
    op.drop_table("organization_rule_audits")
    op.drop_index("ix_org_rules_severity", table_name="organization_rules")
    op.drop_index("ix_org_rules_type", table_name="organization_rules")
    op.drop_index("ix_org_rules_enabled", table_name="organization_rules")
    op.drop_index("ix_org_rules_name", table_name="organization_rules")
    op.drop_table("organization_rules")
