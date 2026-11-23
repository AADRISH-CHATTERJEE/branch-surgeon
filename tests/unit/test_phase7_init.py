"""Tests for Phase 7: PS-4 (refactory init bootstrap)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from refactory.cli.app import app


runner = CliRunner()


class TestInitCommand:
    def test_creates_refactory_dir(self, tmp_path: Path):
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / ".refactory").is_dir()

    def test_creates_rules_yaml(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        rules_file = tmp_path / ".refactory" / "rules.yaml"
        assert rules_file.is_file()
        content = rules_file.read_text()
        assert "rules:" in content

    def test_creates_architecture_yaml(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        arch_file = tmp_path / ".refactory" / "architecture.yaml"
        assert arch_file.is_file()
        content = arch_file.read_text()
        assert "layers:" in content

    def test_creates_company_yaml(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        company_file = tmp_path / ".refactory" / "company.yaml"
        assert company_file.is_file()
        content = company_file.read_text()
        assert "organization:" in content

    def test_creates_prompts_yaml(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        prompts_file = tmp_path / ".refactory" / "prompts.yaml"
        assert prompts_file.is_file()
        content = prompts_file.read_text()
        assert "templates:" in content

    def test_creates_storage_dir(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        assert (tmp_path / ".refactory" / "storage").is_dir()

    def test_creates_database(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        db_file = tmp_path / ".refactory" / "storage" / "refactory.db"
        assert db_file.is_file()

    def test_does_not_overwrite_existing(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        custom = "# Custom rules\nrules: []\n"
        (tmp_path / ".refactory" / "rules.yaml").write_text(custom)
        runner.invoke(app, ["init", str(tmp_path)])
        content = (tmp_path / ".refactory" / "rules.yaml").read_text()
        assert content == custom

    def test_force_overwrites(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        (tmp_path / ".refactory" / "rules.yaml").write_text("custom")
        runner.invoke(app, ["init", str(tmp_path), "--force"])
        content = (tmp_path / ".refactory" / "rules.yaml").read_text()
        assert "rules:" in content
        assert content != "custom"

    def test_output_message(self, tmp_path: Path):
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert "Initialized" in result.output
        assert "Created" in result.output

    def test_skipped_message(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert "Skipped" in result.output

    def test_idempotent(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0

    def test_all_files_created(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        expected = [
            ".refactory/rules.yaml",
            ".refactory/architecture.yaml",
            ".refactory/company.yaml",
            ".refactory/prompts.yaml",
            ".refactory/storage/refactory.db",
        ]
        for f in expected:
            assert (tmp_path / f).exists(), f"Missing: {f}"
