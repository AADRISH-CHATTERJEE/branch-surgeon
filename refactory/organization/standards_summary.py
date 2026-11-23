"""Summarize enabled organization rules into Company Standards panel fields.

GET /rules historically exposed only ``.refactory/company.yaml``. When that file
is absent or incomplete, the Rules Center Company Standards panel looked empty
even though organization policies (branch naming, commits, architecture,
testing) were configured. This module fills those gaps from enabled org rules.
"""

from __future__ import annotations

from typing import Any


_BRANCH_TYPES = frozenset({"branch_naming", "branch"})
_COMMIT_TYPES = frozenset({"commit_message", "commit", "pull_request"})
_ARCH_TYPES = frozenset({"architecture", "architecture_layer", "file_path", "file_pattern"})
_TEST_TYPES = frozenset({"testing", "required_tests"})


def _enabled(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("enabled", True)]


def _type_key(row: dict[str, Any]) -> str:
    return str(row.get("rule_type") or row.get("category") or "").lower()


def _category_key(row: dict[str, Any]) -> str:
    return str(row.get("category") or "").lower()


def _has_field(row: dict[str, Any], field: str) -> bool:
    for c in row.get("conditions") or []:
        if isinstance(c, dict) and str(c.get("field") or "").lower() == field:
            return True
    return False


def _first_pattern(row: dict[str, Any], field: str | None = None) -> str:
    for c in row.get("conditions") or []:
        if not isinstance(c, dict):
            continue
        if field and str(c.get("field") or "").lower() != field:
            continue
        pattern = str(c.get("pattern") or c.get("value") or "")
        if pattern:
            return pattern
    return ""


def _is_branch_rule(row: dict[str, Any]) -> bool:
    key = _type_key(row)
    cat = _category_key(row)
    return (
        key in _BRANCH_TYPES
        or cat in _BRANCH_TYPES
        or "branch" in cat
        or _has_field(row, "branch_name")
    )


def _is_commit_rule(row: dict[str, Any]) -> bool:
    key = _type_key(row)
    cat = _category_key(row)
    return (
        key in _COMMIT_TYPES
        or cat in {"commit_message", "pr_title"}
        or _has_field(row, "commit_message")
    )


def _is_architecture_rule(row: dict[str, Any]) -> bool:
    key = _type_key(row)
    cat = _category_key(row)
    return (
        key in _ARCH_TYPES
        or "architecture" in cat
        or "layer" in cat
        or "forbidden_path" in cat
        or "forbidden_import" in cat
    )


def _is_testing_rule(row: dict[str, Any]) -> bool:
    key = _type_key(row)
    cat = _category_key(row)
    return key in _TEST_TYPES or "test" in cat or "test" in key


def _policy_summary(
    rows: list[dict[str, Any]],
    *,
    kind: str,
    pattern_field: str | None = None,
) -> dict[str, Any] | None:
    if not rows:
        return None
    names = [str(r.get("name") or "unnamed") for r in rows]
    blocking = any(bool(r.get("blocking")) for r in rows)
    pattern = ""
    message = ""
    for r in rows:
        if not pattern:
            pattern = _first_pattern(r, pattern_field)
        if not message:
            message = str(r.get("message") or r.get("description") or "")
    summary: dict[str, Any] = {
        "configured": True,
        "source": "organization_rules",
        "policy": kind,
        "block": blocking,
        "blocking": blocking,
        "rule_count": len(rows),
        "rule_names": names,
        "message": message,
    }
    if pattern:
        summary["pattern"] = pattern
    if kind == "testing":
        summary["require_tests"] = True
    if kind == "architecture":
        # Keep shape compatible with company.yaml architecture block.
        summary["forbidden_dependencies"] = []
    return summary


def summarize_org_rule_policies(
    org_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build branch/commit/architecture/testing policy summaries from org rules."""
    enabled = _enabled(org_rules)
    branch_rows = [r for r in enabled if _is_branch_rule(r)]
    commit_rows = [r for r in enabled if _is_commit_rule(r)]
    arch_rows = [r for r in enabled if _is_architecture_rule(r)]
    test_rows = [r for r in enabled if _is_testing_rule(r)]

    branch = _policy_summary(branch_rows, kind="branch", pattern_field="branch_name")
    commit = _policy_summary(commit_rows, kind="commit", pattern_field="commit_message")
    architecture = _policy_summary(arch_rows, kind="architecture")
    testing = _policy_summary(test_rows, kind="testing")

    return {
        "branch": branch,
        "commit": commit,
        "architecture": architecture,
        "testing": testing,
        # Explicit aliases requested for API consumers / future UI.
        "branch_policy": branch,
        "commit_policy": commit,
        "architecture_policy": architecture,
        "testing_policy": testing,
    }


def merge_standards_with_org_rules(
    company_standards: dict[str, Any],
    org_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """Prefer company.yaml policies; fill gaps from enabled organization rules."""
    derived = summarize_org_rule_policies(org_rules)
    out = dict(company_standards or {})

    yaml_keys = ("branch", "commit", "architecture", "testing")
    filled_from_org: list[str] = []
    for key in yaml_keys:
        if out.get(key):
            continue
        if derived.get(key):
            out[key] = derived[key]
            filled_from_org.append(key)

    for alias, key in (
        ("branch_policy", "branch"),
        ("commit_policy", "commit"),
        ("architecture_policy", "architecture"),
        ("testing_policy", "testing"),
    ):
        out[alias] = out.get(key)

    sources: list[str] = []
    if any((company_standards or {}).get(k) for k in yaml_keys):
        sources.append("company.yaml")
    if filled_from_org:
        sources.append("organization_rules")
    out["standards_source"] = "+".join(sources) if sources else "none"
    out["organization_rule_policies"] = {
        k: derived[k] for k in yaml_keys if derived.get(k)
    }
    return out
