"""Tests for CompanyConfiguration, PromptTemplateService, and Auth interfaces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from refactory.auth import (
    AuthContext,
    Organization,
    RepositoryPermission,
    User,
    UserRole,
)
from refactory.config.company import (
    BranchStrategy,
    CodingStandards,
    CommitConvention,
    CompanyConfiguration,
    DocumentationRequirements,
    ProjectTestRequirements,
    ReviewPolicy,
    SecurityPolicy,
)
from refactory.prompts import PromptTemplate, PromptTemplateService


# ===========================================================================
# Company Configuration Tests
# ===========================================================================

class TestCompanyConfiguration:
    def test_default_config(self):
        config = CompanyConfiguration()
        assert config.name == "default"
        assert config.coding_standards.max_function_lines == 50
        assert config.review_policy.min_reviewers == 1

    def test_coding_standards(self):
        cs = CodingStandards(max_function_lines=100, naming_convention="camelCase")
        assert cs.max_function_lines == 100
        assert cs.naming_convention == "camelCase"

    def test_review_policy(self):
        rp = ReviewPolicy(min_reviewers=2, require_owner_review=True)
        assert rp.min_reviewers == 2
        assert rp.require_owner_review is True

    def test_security_policy(self):
        sp = SecurityPolicy(block_on_critical=True, forbidden_apis=["eval", "exec"])
        assert sp.block_on_critical is True
        assert "eval" in sp.forbidden_apis

    def test_branch_strategy(self):
        bs = BranchStrategy(default_branch="develop")
        assert bs.default_branch == "develop"

    def test_commit_convention(self):
        cc = CommitConvention(max_subject_length=50)
        assert cc.max_subject_length == 50

    def test_test_requirements(self):
        tr = ProjectTestRequirements(min_coverage_percent=90.0)
        assert tr.min_coverage_percent == 90.0

    def test_documentation_requirements(self):
        dr = DocumentationRequirements(require_readme=True)
        assert dr.require_readme is True

    def test_load_from_file(self, tmp_path: Path):
        config_data = {
            "name": "acme",
            "coding_standards": {"max_function_lines": 75},
            "review_policy": {"min_reviewers": 2},
        }
        config_file = tmp_path / "company.json"
        config_file.write_text(json.dumps(config_data))
        config = CompanyConfiguration.load_from_file(config_file)
        assert config.name == "acme"
        assert config.coding_standards.max_function_lines == 75

    def test_load_from_repo(self, tmp_path: Path):
        refactory_dir = tmp_path / ".refactory"
        refactory_dir.mkdir()
        config_data = {"name": "from-repo"}
        (refactory_dir / "company.json").write_text(json.dumps(config_data))
        config = CompanyConfiguration.load_from_repo(tmp_path)
        assert config.name == "from-repo"

    def test_load_from_repo_missing(self, tmp_path: Path):
        config = CompanyConfiguration.load_from_repo(tmp_path)
        assert config.name == "default"

    def test_merge_with(self):
        base = CompanyConfiguration(name="base", coding_standards=CodingStandards(max_function_lines=50))
        override = CompanyConfiguration(name="override", coding_standards=CodingStandards(max_function_lines=100))
        merged = base.merge_with(override)
        assert merged.coding_standards.max_function_lines == 100

    def test_save_to_file(self, tmp_path: Path):
        config = CompanyConfiguration(name="saved")
        path = tmp_path / "out" / "config.json"
        config.save_to_file(path)
        assert path.is_file()
        loaded = json.loads(path.read_text())
        assert loaded["name"] == "saved"

    def test_allowed_frameworks(self):
        config = CompanyConfiguration(allowed_frameworks=["flask", "fastapi"])
        assert "flask" in config.allowed_frameworks

    def test_restricted_frameworks(self):
        config = CompanyConfiguration(restricted_frameworks=["django"])
        assert "django" in config.restricted_frameworks


# ===========================================================================
# Prompt Template Tests
# ===========================================================================

class TestPromptTemplateService:
    def test_default_templates_exist(self):
        svc = PromptTemplateService()
        assert svc.get("review") is not None
        assert svc.get("architecture") is not None
        assert svc.get("documentation") is not None
        assert svc.get("patch") is not None
        assert svc.get("test_generation") is not None

    def test_get_nonexistent(self):
        svc = PromptTemplateService()
        assert svc.get("nonexistent") is None

    def test_register_custom(self):
        svc = PromptTemplateService()
        svc.register(PromptTemplate(name="custom", system_prompt="Hello"))
        assert svc.get("custom") is not None
        assert svc.get("custom").system_prompt == "Hello"

    def test_override_existing(self):
        svc = PromptTemplateService()
        svc.register(PromptTemplate(name="review", system_prompt="Custom review"))
        assert svc.get("review").system_prompt == "Custom review"

    def test_list_templates(self):
        svc = PromptTemplateService()
        templates = svc.list_templates()
        assert len(templates) >= 5

    def test_render(self):
        svc = PromptTemplateService()
        sys_prompt, user_prompt = svc.render("review", context="test code")
        assert "reviewer" in sys_prompt.lower()
        assert "test code" in user_prompt

    def test_render_nonexistent(self):
        svc = PromptTemplateService()
        sys_prompt, user_prompt = svc.render("missing")
        assert sys_prompt == ""
        assert user_prompt == ""

    def test_categories(self):
        svc = PromptTemplateService()
        cats = svc.categories
        assert "review" in cats
        assert "security" in cats

    def test_load_from_file(self, tmp_path: Path):
        data = {"templates": {"my_prompt": {"system_prompt": "Custom", "category": "test"}}}
        path = tmp_path / "prompts.json"
        path.write_text(json.dumps(data))
        svc = PromptTemplateService()
        count = svc.load_from_file(path)
        assert count == 1
        assert svc.get("my_prompt") is not None

    def test_load_from_repo(self, tmp_path: Path):
        refactory_dir = tmp_path / ".refactory"
        refactory_dir.mkdir()
        data = {"templates": {"repo_prompt": {"system_prompt": "Repo"}}}
        (refactory_dir / "prompts.json").write_text(json.dumps(data))
        svc = PromptTemplateService()
        count = svc.load_from_repo(tmp_path)
        assert count == 1

    def test_load_from_missing_file(self, tmp_path: Path):
        svc = PromptTemplateService()
        count = svc.load_from_repo(tmp_path)
        assert count == 0

    def test_template_model(self):
        t = PromptTemplate(name="test", max_tokens=1000, temperature=0.5)
        assert t.max_tokens == 1000
        assert t.temperature == 0.5


# ===========================================================================
# Authentication Readiness Tests
# ===========================================================================

class TestAuthInterfaces:
    def test_user_model(self):
        u = User(id="1", email="dev@co.com", name="Dev", role=UserRole.DEVELOPER)
        assert u.role == UserRole.DEVELOPER
        assert u.is_active is True

    def test_organization_model(self):
        org = Organization(id="1", name="Acme", slug="acme")
        assert org.name == "Acme"

    def test_repository_permission(self):
        perm = RepositoryPermission(
            repository_id="repo1", user_id="user1",
            role=UserRole.DEVELOPER, can_write=True,
        )
        assert perm.can_write is True

    def test_auth_context_unauthenticated(self):
        ctx = AuthContext()
        assert ctx.authenticated is False
        assert ctx.has_permission("repo1", UserRole.DEVELOPER) is False

    def test_auth_context_admin(self):
        ctx = AuthContext(
            user=User(id="1", role=UserRole.ADMIN),
            authenticated=True,
        )
        assert ctx.has_permission("any-repo", UserRole.DEVELOPER) is True

    def test_auth_context_with_permission(self):
        ctx = AuthContext(
            user=User(id="1", role=UserRole.DEVELOPER),
            authenticated=True,
            permissions=[
                RepositoryPermission(repository_id="repo1", user_id="1", role=UserRole.DEVELOPER),
            ],
        )
        assert ctx.has_permission("repo1", UserRole.DEVELOPER) is True
        assert ctx.has_permission("repo1", UserRole.ADMIN) is False

    def test_auth_context_no_permission(self):
        ctx = AuthContext(
            user=User(id="1", role=UserRole.READ_ONLY),
            authenticated=True,
            permissions=[
                RepositoryPermission(repository_id="repo1", user_id="1", role=UserRole.READ_ONLY),
            ],
        )
        assert ctx.has_permission("repo1", UserRole.DEVELOPER) is False

    def test_user_roles(self):
        assert UserRole.ADMIN == "admin"
        assert UserRole.DEVELOPER == "developer"
        assert UserRole.REVIEWER == "reviewer"
        assert UserRole.READ_ONLY == "read_only"

    def test_organization_members(self):
        org = Organization(members=["user1", "user2"])
        assert len(org.members) == 2
