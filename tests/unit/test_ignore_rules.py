"""Tests for configurable ignore rules (.refactoryignore)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from refactory.core.ignore import (
    IGNORE_FILENAME,
    IgnoreRules,
    _DEFAULT_PATTERNS,
    load_ignore_rules,
)


class TestIgnoreRulesDefaults:
    def test_default_patterns_loaded_when_no_input(self):
        rules = IgnoreRules()
        assert rules.is_ignored("build/foo.py")
        assert rules.is_ignored("dist/bar.py")
        assert rules.is_ignored("node_modules/lodash/index.js")
        assert rules.is_ignored("__pycache__/foo.pyc")

    def test_production_code_not_ignored(self):
        rules = IgnoreRules()
        assert not rules.is_ignored("src/app.py")
        assert not rules.is_ignored("refactory/core/config.py")

    def test_venv_ignored(self):
        rules = IgnoreRules()
        assert rules.is_ignored(".venv/lib/python3.11/site-packages/foo.py")
        assert rules.is_ignored("venv/bin/activate")

    def test_migrations_ignored(self):
        rules = IgnoreRules()
        assert rules.is_ignored("migrations/001_initial.py")

    def test_coverage_ignored(self):
        rules = IgnoreRules()
        assert rules.is_ignored("coverage/report.html")


class TestIgnoreRulesCustom:
    def test_custom_patterns(self):
        rules = IgnoreRules(patterns=["logs/", "*.tmp"])
        assert rules.is_ignored("logs/debug.log")
        assert rules.is_ignored("output.tmp")
        assert not rules.is_ignored("src/app.py")

    def test_negation(self):
        rules = IgnoreRules(patterns=["vendor/", "!vendor/important.py"])
        assert not rules.is_ignored("vendor/important.py")
        assert rules.is_ignored("vendor/other.py")

    def test_comments_ignored(self):
        rules = IgnoreRules(patterns=["# this is a comment", "temp/"])
        assert rules.is_ignored("temp/foo")
        assert not rules.is_ignored("src/main.py")

    def test_blank_lines_ignored(self):
        rules = IgnoreRules(patterns=["", "  ", "temp/"])
        assert rules.is_ignored("temp/foo")

    def test_glob_patterns(self):
        rules = IgnoreRules(patterns=["*.pyc", "*.pyo"])
        assert rules.is_ignored("module.pyc")
        assert rules.is_ignored("some/path/module.pyo")

    def test_nested_directory(self):
        rules = IgnoreRules(patterns=["dist/"])
        assert rules.is_ignored("project/dist/bundle.js")

    def test_windows_paths(self):
        rules = IgnoreRules(patterns=["build/"])
        assert rules.is_ignored("project\\build\\output.js")


class TestIgnoreRulesFile:
    def test_load_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ignore_file = root / IGNORE_FILENAME
            ignore_file.write_text("custom_dir/\n*.log\n", encoding="utf-8")
            rules = IgnoreRules(root=root)
            assert rules.is_ignored("custom_dir/foo.py")
            assert rules.is_ignored("server.log")

    def test_no_file_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            rules = IgnoreRules(root=root)
            assert rules.is_ignored("build/foo.py")

    def test_load_ignore_rules_function(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            rules = load_ignore_rules(root)
            assert rules.is_ignored("node_modules/foo.js")


class TestIgnoredDirs:
    def test_returns_dir_names(self):
        rules = IgnoreRules(patterns=["build/", "dist/", "*.pyc"])
        dirs = rules.ignored_dirs()
        assert "build" in dirs
        assert "dist" in dirs
        assert len(dirs) == 2


class TestPathNormalization:
    def test_forward_slash_normalization(self):
        rules = IgnoreRules(patterns=["vendor/"])
        assert rules.is_ignored("project/vendor/lib.py")

    def test_case_insensitive_matching(self):
        rules = IgnoreRules(patterns=["BUILD/"])
        assert rules.is_ignored("project/Build/output.js")

    def test_generated_dir(self):
        rules = IgnoreRules()
        assert rules.is_ignored("generated/proto/service.py")
