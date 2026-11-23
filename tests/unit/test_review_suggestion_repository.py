"""Repository / persistence coverage for review suggestion lifecycle fields."""

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


def test_update_suggestion_status_sets_lifecycle_timestamps(persistence):
    repo = persistence.get_or_create_repository(name="r", root_path="/tmp/sug-repo")
    review = persistence.persist_review(
        repository_id=repo["id"],
        suggestions=[{"file": "a.py", "title": "t", "category": "style"}],
    )
    # Fetch via unit of work
    with persistence.unit_of_work() as uow:
        rows = uow.review_suggestions.list_by_review(review["id"])
        sid = rows[0].id

    pending = persistence.get_review_suggestion(sid)
    assert pending["status"] == "pending"
    assert pending["created_at"] is not None

    resolved = persistence.update_review_suggestion_status(
        sid, "resolved", updated_by="tester"
    )
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None
    assert resolved["ignored_at"] is None
    assert resolved["updated_by"] == "tester"
    assert resolved["updated_at"] is not None

    ignored = persistence.update_review_suggestion_status(
        sid, "ignored", updated_by="tester"
    )
    assert ignored["status"] == "ignored"
    assert ignored["ignored_at"] is not None
    assert ignored["resolved_at"] is None
