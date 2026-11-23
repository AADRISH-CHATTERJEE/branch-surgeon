"""Tests for ArchitecturePolicyService and policy models."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from refactory.policies.models import (
    ArchitectureLayer,
    ArchitecturePolicy,
    PolicyReport,
    PolicyViolation,
    ViolationType,
)
from refactory.policies.service import ArchitecturePolicyService


@pytest.fixture
def service():
    from loguru import logger
    return ArchitecturePolicyService(
        logger=logger,
        parser_service=MagicMock(),
    )


@pytest.fixture
def standard_policy() -> ArchitecturePolicy:
    return ArchitecturePolicy(
        name="standard",
        layers=[
            ArchitectureLayer(
                name="presentation",
                patterns=[r"controllers/", r"views/", r"api/"],
                allowed_dependencies=["service"],
            ),
            ArchitectureLayer(
                name="service",
                patterns=[r"services/", r"service/"],
                allowed_dependencies=["repository"],
            ),
            ArchitectureLayer(
                name="repository",
                patterns=[r"repositories/", r"repo/", r"db/"],
                allowed_dependencies=[],
            ),
        ],
    )


# ===========================================================================
# Policy Model Tests
# ===========================================================================

class TestPolicyModels:
    def test_architecture_layer(self):
        layer = ArchitectureLayer(name="service", patterns=["service/"])
        assert layer.name == "service"

    def test_architecture_policy(self):
        p = ArchitecturePolicy(name="test")
        assert p.layers == []

    def test_policy_violation(self):
        v = PolicyViolation(
            violation_type=ViolationType.LAYER_VIOLATION,
            source_file="a.py",
            target_file="b.py",
        )
        assert v.violation_type == ViolationType.LAYER_VIOLATION

    def test_policy_report_default(self):
        r = PolicyReport()
        assert r.passed is True
        assert r.violations == []

    def test_violation_types(self):
        assert ViolationType.LAYER_VIOLATION == "layer_violation"
        assert ViolationType.CIRCULAR_DEPENDENCY == "circular_dependency"
        assert ViolationType.FORBIDDEN_IMPORT == "forbidden_import"

    def test_layer_with_allowed_deps(self):
        layer = ArchitectureLayer(
            name="api",
            patterns=["api/"],
            allowed_dependencies=["service", "models"],
        )
        assert "service" in layer.allowed_dependencies


# ===========================================================================
# Architecture Policy Service Tests
# ===========================================================================

class TestArchitecturePolicyService:
    def test_load_policy(self, service: ArchitecturePolicyService, standard_policy: ArchitecturePolicy):
        service.load_policy(standard_policy)
        assert service.policy is not None
        assert service.policy.name == "standard"

    def test_no_policy_passes(self, service: ArchitecturePolicyService):
        result = service.evaluate({})
        assert result.passed is True

    def test_valid_imports_pass(self, service: ArchitecturePolicyService, standard_policy: ArchitecturePolicy):
        service.load_policy(standard_policy)
        file_imports = {
            "controllers/user_controller.py": ["services/user_service.py"],
            "services/user_service.py": ["repositories/user_repo.py"],
        }
        result = service.evaluate(file_imports)
        assert result.passed is True

    def test_layer_violation_detected(self, service: ArchitecturePolicyService, standard_policy: ArchitecturePolicy):
        service.load_policy(standard_policy)
        file_imports = {
            "controllers/user_controller.py": ["repositories/user_repo.py"],
        }
        result = service.evaluate(file_imports)
        assert result.passed is False
        assert len(result.violations) == 1
        assert result.violations[0].source_layer == "presentation"
        assert result.violations[0].target_layer == "repository"

    def test_same_layer_ok(self, service: ArchitecturePolicyService, standard_policy: ArchitecturePolicy):
        service.load_policy(standard_policy)
        file_imports = {
            "services/auth_service.py": ["services/token_service.py"],
        }
        result = service.evaluate(file_imports)
        assert result.passed is True

    def test_unknown_layer_ignored(self, service: ArchitecturePolicyService, standard_policy: ArchitecturePolicy):
        service.load_policy(standard_policy)
        file_imports = {
            "utils/helpers.py": ["services/user_service.py"],
        }
        result = service.evaluate(file_imports)
        assert result.passed is True

    def test_multiple_violations(self, service: ArchitecturePolicyService, standard_policy: ArchitecturePolicy):
        service.load_policy(standard_policy)
        file_imports = {
            "controllers/a.py": ["repositories/x.py"],
            "controllers/b.py": ["db/y.py"],
        }
        result = service.evaluate(file_imports)
        assert len(result.violations) == 2

    def test_files_checked_count(self, service: ArchitecturePolicyService, standard_policy: ArchitecturePolicy):
        service.load_policy(standard_policy)
        file_imports = {
            "controllers/a.py": ["services/b.py"],
            "services/b.py": ["repositories/c.py"],
            "utils/d.py": ["os"],
        }
        result = service.evaluate(file_imports)
        assert result.files_checked == 3

    def test_layers_checked_count(self, service: ArchitecturePolicyService, standard_policy: ArchitecturePolicy):
        service.load_policy(standard_policy)
        result = service.evaluate({})
        assert result.layers_checked == 3

    def test_load_from_config(self, service: ArchitecturePolicyService):
        config = {
            "name": "custom",
            "layers": [
                {"name": "ui", "patterns": ["ui/"], "allowed_dependencies": ["api"]},
                {"name": "api", "patterns": ["api/"], "allowed_dependencies": []},
            ],
        }
        service.load_policy_from_config(config)
        assert service.policy is not None
        assert service.policy.name == "custom"
        assert len(service.policy.layers) == 2

    def test_empty_imports(self, service: ArchitecturePolicyService, standard_policy: ArchitecturePolicy):
        service.load_policy(standard_policy)
        result = service.evaluate({})
        assert result.passed is True
        assert result.files_checked == 0

    def test_report_serializable(self, service: ArchitecturePolicyService, standard_policy: ArchitecturePolicy):
        service.load_policy(standard_policy)
        file_imports = {"controllers/a.py": ["repositories/b.py"]}
        result = service.evaluate(file_imports)
        data = result.model_dump()
        assert "violations" in data

    def test_violation_description(self, service: ArchitecturePolicyService, standard_policy: ArchitecturePolicy):
        service.load_policy(standard_policy)
        file_imports = {"controllers/a.py": ["repositories/b.py"]}
        result = service.evaluate(file_imports)
        assert "presentation" in result.violations[0].description
        assert "repository" in result.violations[0].description
