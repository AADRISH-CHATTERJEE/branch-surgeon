"""Database engine management and initialization."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from refactory.db.base import Base

if TYPE_CHECKING:
    from loguru import Logger

_DEFAULT_DB_DIR = Path.home() / ".refactory" / "db"


def _get_default_url(repo_root: Path | None = None) -> str:
    """Build a SQLite URL scoped to the repository or user home."""
    if repo_root:
        db_dir = repo_root / ".refactory" / "db"
    else:
        db_dir = _DEFAULT_DB_DIR
    db_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_dir / 'refactory.db'}"


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL mode and foreign keys for SQLite connections."""
    import sqlite3

    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class DatabaseManager:
    """Creates and owns the SQLAlchemy engine.

    Responsible for engine lifecycle, table creation (dev/test), and
    providing the engine to SessionFactory.
    """

    def __init__(
        self,
        database_url: str | None = None,
        *,
        repo_root: Path | None = None,
        echo: bool = False,
        logger: "Logger | None" = None,
    ) -> None:
        self._url = database_url or _get_default_url(repo_root)
        self._logger = logger

        connect_args: dict = {}
        if self._url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        self._engine = create_engine(
            self._url,
            echo=echo,
            connect_args=connect_args,
            pool_pre_ping=True,
        )

        if self._logger:
            self._logger.debug("DatabaseManager initialised: {}", self._url)

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def url(self) -> str:
        return self._url

    def create_all(self) -> None:
        """Create all tables declared on Base (dev / first-run convenience)."""
        Base.metadata.create_all(self._engine)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        """Apply additive SQLite column upgrades ``create_all`` cannot perform.

        Existing local DBs keep old table shapes; SQLAlchemy create_all never
        ALTERs them. Without this, ORM columns added in later phases (e.g.
        ``db_patches.status``) cause OperationalError on insert.
        """
        if not self._url.startswith("sqlite"):
            return
        # table -> list of (column, DDL type fragment)
        upgrades: dict[str, list[tuple[str, str]]] = {
            "db_patches": [
                ("status", "VARCHAR(30) DEFAULT 'generated'"),
                ("applied_at", "DATETIME"),
                ("applied_by", "VARCHAR(100)"),
                ("git_commit", "VARCHAR(40)"),
                ("failure_reason", "TEXT"),
                ("rollback_metadata", "JSON"),
            ],
            "db_recommendations": [
                ("reasoning", "TEXT DEFAULT ''"),
                ("affected_files", "JSON"),
                ("impact", "JSON"),
                ("effort", "VARCHAR(10) DEFAULT ''"),
                ("confidence", "FLOAT"),
                ("resolution_notes", "TEXT DEFAULT ''"),
                ("verification_status", "VARCHAR(40) DEFAULT 'unverified'"),
                ("patch_history", "JSON"),
                ("updated_at", "DATETIME"),
                ("resolved_at", "DATETIME"),
                ("ignored_at", "DATETIME"),
                ("updated_by", "VARCHAR(100)"),
            ],
            "db_review_suggestions": [
                ("status", "VARCHAR(20) DEFAULT 'pending'"),
                ("created_at", "DATETIME"),
                ("updated_at", "DATETIME"),
                ("resolved_at", "DATETIME"),
                ("ignored_at", "DATETIME"),
                ("updated_by", "VARCHAR(100)"),
                ("recommendation_id", "VARCHAR(36)"),
            ],
            "analysis_history": [
                ("analysis_run_id", "VARCHAR(36)"),
                ("organization_id", "VARCHAR(36)"),
                ("created_by_user", "VARCHAR(100)"),
            ],
            "organization_rules": [
                ("organization_id", "VARCHAR(36)"),
                ("team_id", "VARCHAR(36)"),
                # Defensive: older local DBs created before the column existed.
                ("blocking", "BOOLEAN DEFAULT 0"),
            ],
        }
        with self._engine.begin() as conn:
            for table, columns in upgrades.items():
                existing = {
                    row[1]
                    for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                }
                if not existing:
                    continue  # table not created yet / create_all will handle
                for col_name, col_type in columns:
                    if col_name in existing:
                        continue
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                    )
                    if self._logger:
                        self._logger.info(
                            "SQLite schema upgrade: {}.{} added", table, col_name
                        )
                if table == "db_patches":
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_db_patch_status "
                            "ON db_patches (status)"
                        )
                    )

    def drop_all(self) -> None:
        """Drop all tables (testing only)."""
        Base.metadata.drop_all(self._engine)

    def dispose(self) -> None:
        """Dispose of the engine connection pool."""
        self._engine.dispose()