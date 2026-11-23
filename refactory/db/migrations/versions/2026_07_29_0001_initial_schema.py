"""Create initial schema for all 10 entities.

Revision ID: 0001
Revises: None
Create Date: 2026-07-29
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Repository ---
    op.create_table(
        "db_repositories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("root_path", sa.Text, nullable=False, unique=True),
        sa.Column("default_branch", sa.String(100), server_default="main"),
        sa.Column("remote_url", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_db_repo_name", "db_repositories", ["name"])
    op.create_index("ix_db_repo_root_path", "db_repositories", ["root_path"])

    # --- File ---
    op.create_table(
        "db_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("db_repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("language", sa.String(50), server_default="unknown"),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("size", sa.Integer, server_default="0"),
        sa.Column("last_indexed", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_db_file_repo_path", "db_files", ["repository_id", "path"], unique=True)
    op.create_index("ix_db_file_language", "db_files", ["language"])

    # --- Symbol ---
    op.create_table(
        "db_symbols",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "file_id",
            sa.String(36),
            sa.ForeignKey("db_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("line", sa.Integer, nullable=True),
        sa.Column("column", sa.Integer, nullable=True),
        sa.Column("signature", sa.Text, nullable=True),
    )
    op.create_index("ix_db_symbol_file", "db_symbols", ["file_id"])
    op.create_index("ix_db_symbol_name", "db_symbols", ["name"])
    op.create_index("ix_db_symbol_type", "db_symbols", ["type"])

    # --- Import ---
    op.create_table(
        "db_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "file_id",
            sa.String(36),
            sa.ForeignKey("db_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("module", sa.String(255), nullable=False),
        sa.Column("symbol", sa.String(255), nullable=True),
    )
    op.create_index("ix_db_import_file", "db_imports", ["file_id"])
    op.create_index("ix_db_import_module", "db_imports", ["module"])

    # --- Review ---
    op.create_table(
        "db_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("db_repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pr_number", sa.Integer, nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("risk", sa.String(20), server_default="unknown"),
        sa.Column("confidence", sa.Float, server_default="0.0"),
        sa.Column("summary", sa.Text, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_db_review_repo", "db_reviews", ["repository_id"])
    op.create_index("ix_db_review_pr", "db_reviews", ["pr_number"])
    op.create_index("ix_db_review_created", "db_reviews", ["created_at"])

    # --- ReviewSuggestion ---
    op.create_table(
        "db_review_suggestions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "review_id",
            sa.String(36),
            sa.ForeignKey("db_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file", sa.Text, nullable=True),
        sa.Column("line", sa.Integer, nullable=True),
        sa.Column("severity", sa.String(20), server_default="info"),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("title", sa.String(500), server_default=""),
        sa.Column("explanation", sa.Text, server_default=""),
        sa.Column("suggested_fix", sa.Text, server_default=""),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("estimated_impact", sa.Text, server_default=""),
    )
    op.create_index("ix_db_suggestion_review", "db_review_suggestions", ["review_id"])
    op.create_index("ix_db_suggestion_severity", "db_review_suggestions", ["severity"])

    # --- Recommendation ---
    op.create_table(
        "db_recommendations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("db_repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("priority", sa.String(20), server_default="medium"),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_db_rec_repo", "db_recommendations", ["repository_id"])
    op.create_index("ix_db_rec_type", "db_recommendations", ["type"])
    op.create_index("ix_db_rec_priority", "db_recommendations", ["priority"])
    op.create_index("ix_db_rec_status", "db_recommendations", ["status"])

    # --- Embedding ---
    op.create_table(
        "db_embeddings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "file_id",
            sa.String(36),
            sa.ForeignKey("db_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_id", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(100), server_default=""),
        sa.Column("model", sa.String(100), server_default=""),
        sa.Column("vector_reference", sa.Text, server_default=""),
    )
    op.create_index("ix_db_emb_file", "db_embeddings", ["file_id"])
    op.create_index("ix_db_emb_chunk", "db_embeddings", ["chunk_id"])

    # --- GraphNode ---
    op.create_table(
        "db_graph_nodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("db_repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
    )
    op.create_index("ix_db_gnode_repo", "db_graph_nodes", ["repository_id"])
    op.create_index("ix_db_gnode_name", "db_graph_nodes", ["name"])
    op.create_index("ix_db_gnode_type", "db_graph_nodes", ["type"])

    # --- GraphEdge ---
    op.create_table(
        "db_graph_edges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_node",
            sa.String(36),
            sa.ForeignKey("db_graph_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_node",
            sa.String(36),
            sa.ForeignKey("db_graph_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relationship", sa.String(100), nullable=False),
    )
    op.create_index("ix_db_gedge_source", "db_graph_edges", ["source_node"])
    op.create_index("ix_db_gedge_target", "db_graph_edges", ["target_node"])
    op.create_index("ix_db_gedge_rel", "db_graph_edges", ["relationship"])


def downgrade() -> None:
    op.drop_table("db_graph_edges")
    op.drop_table("db_graph_nodes")
    op.drop_table("db_embeddings")
    op.drop_table("db_recommendations")
    op.drop_table("db_review_suggestions")
    op.drop_table("db_reviews")
    op.drop_table("db_imports")
    op.drop_table("db_symbols")
    op.drop_table("db_files")
    op.drop_table("db_repositories")
