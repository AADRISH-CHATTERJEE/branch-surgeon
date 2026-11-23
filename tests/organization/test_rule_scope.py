"""Phase 11.5 — org/team rule scope merge."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from refactory.db.database import DatabaseManager
from refactory.db.session import SessionFactory
from refactory.organization.service import OrganizationRuleService


@pytest.fixture()
def rule_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OrganizationRuleService:
    db_url = f"sqlite:///{tmp_path / 'rules.db'}"
    manager = DatabaseManager(database_url=db_url)
    manager.create_all()
    sessions = SessionFactory(manager.engine)

    class _Log:
        def info(self, *a, **k):  # noqa: ANN001
            return None

        def warning(self, *a, **k):  # noqa: ANN001
            return None

        def debug(self, *a, **k):  # noqa: ANN001
            return None

    svc = OrganizationRuleService(logger=_Log(), session_factory=sessions)  # type: ignore[arg-type]
    # Avoid seeding default demo rules for this unit test
    monkeypatch.setattr(svc, "ensure_defaults", lambda: 0)
    return svc


def test_effective_scope_team_overrides_org_name(
    rule_service: OrganizationRuleService,
) -> None:
    org_id = str(uuid4())
    team_id = str(uuid4())
    rule_service.create_rule(
        {
            "name": "Security baseline",
            "rule_type": "security",
            "severity": "warning",
            "message": "org",
            "organization_id": org_id,
            "team_id": None,
        }
    )
    rule_service.create_rule(
        {
            "name": "Security baseline",
            "rule_type": "security",
            "severity": "error",
            "message": "team",
            "organization_id": org_id,
            "team_id": team_id,
        }
    )
    effective = rule_service.list_rules(
        organization_id=org_id, team_id=team_id, scope="effective"
    )
    by_name = {r["name"]: r for r in effective}
    assert by_name["Security baseline"]["message"] == "team"
    assert by_name["Security baseline"]["source"] == "team"

    engine_rules = rule_service.enabled_as_rules(
        organization_id=org_id, team_id=team_id
    )
    assert any(r.source == "team" for r in engine_rules)
