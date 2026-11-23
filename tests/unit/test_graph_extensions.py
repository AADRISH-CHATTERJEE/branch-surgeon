"""Tests for repository knowledge graph extensions (Task 11)."""

from __future__ import annotations

from refactory.graph.models import FileNode, NodeKind


class TestFileNodeExtensions:
    def test_ownership_field(self):
        node = FileNode(
            id="f1",
            kind=NodeKind.FILE,
            name="auth.py",
            ownership="team-security",
        )
        assert node.ownership == "team-security"

    def test_business_domain_field(self):
        node = FileNode(
            id="f1",
            kind=NodeKind.FILE,
            name="billing.py",
            business_domain="revenue",
        )
        assert node.business_domain == "revenue"

    def test_entry_point_field(self):
        node = FileNode(
            id="f1",
            kind=NodeKind.FILE,
            name="main.py",
            is_entry_point=True,
        )
        assert node.is_entry_point is True

    def test_external_api_field(self):
        node = FileNode(
            id="f1",
            kind=NodeKind.FILE,
            name="api.py",
            is_external_api=True,
        )
        assert node.is_external_api is True

    def test_service_name_field(self):
        node = FileNode(
            id="f1",
            kind=NodeKind.FILE,
            name="user_service.py",
            service_name="user-service",
        )
        assert node.service_name == "user-service"

    def test_defaults_empty(self):
        node = FileNode(
            id="f1",
            kind=NodeKind.FILE,
            name="app.py",
        )
        assert node.ownership == ""
        assert node.business_domain == ""
        assert node.is_entry_point is False
        assert node.is_external_api is False
        assert node.service_name == ""

    def test_backward_compatible(self):
        node = FileNode(
            id="f1",
            kind=NodeKind.FILE,
            name="old.py",
            language="python",
            content_hash="abc123",
            import_count=5,
            symbol_count=10,
        )
        assert node.language == "python"
        assert node.import_count == 5
