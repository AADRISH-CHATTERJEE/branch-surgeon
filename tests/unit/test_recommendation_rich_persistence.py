"""Repository persistence for enriched recommendation fields."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from refactory.db.base import Base
from refactory.db.persistence import PersistenceService
from refactory.db.session import SessionFactory


@pytest.fixture()
def persistence():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    factory = SessionFactory(eng)
    svc = PersistenceService(factory, logger=MagicMock())
    yield svc
    eng.dispose()


def test_persist_and_update_lifecycle_fields(persistence: PersistenceService):
    repo = persistence.get_or_create_repository(name="r", root_path="/tmp/rich-rec")
    rid = repo["id"]
    persistence.persist_recommendations(
        rid,
        [
            {
                "id": "R-RICH",
                "type": "security",
                "priority": "critical",
                "title": "Hardcoded secret",
                "description": "desc",
                "status": "pending",
                "reasoning": "Token validator ignores username",
                "affected_files": ["auth.py", "login.py"],
                "impact": ["Security", "API"],
                "effort": "S",
                "confidence": 0.95,
            }
        ],
    )
    row = persistence.get_recommendation("R-RICH")
    assert row is not None
    assert row["reasoning"].startswith("Token")
    assert row["affected_files"] == ["auth.py", "login.py"]
    assert row["effort"] == "S"
    assert row["confidence"] == 0.95
    assert "Security" in row["impact"]

    resolved = persistence.update_recommendation_status(
        "R-RICH", "resolved", updated_by="tester", resolution_notes="Fixed in abc"
    )
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"]
    assert resolved["updated_by"] == "tester"
    assert resolved["resolution_notes"] == "Fixed in abc"
    assert resolved["ignored_at"] is None

    ignored = persistence.update_recommendation_status(
        "R-RICH", "ignored", updated_by="tester"
    )
    assert ignored["status"] == "ignored"
    assert ignored["ignored_at"]
    assert ignored["resolved_at"] is None


def test_applied_does_not_set_resolved_at(persistence: PersistenceService):
    repo = persistence.get_or_create_repository(name="r2", root_path="/tmp/rich-app")
    persistence.persist_recommendations(
        repo["id"],
        [
            {
                "id": "R-APP",
                "type": "testing",
                "priority": "medium",
                "title": "Add tests",
                "description": "d",
                "status": "pending",
            }
        ],
    )
    applied = persistence.update_recommendation_status("R-APP", "applied")
    assert applied["status"] == "applied"
    assert applied["resolved_at"] is None
