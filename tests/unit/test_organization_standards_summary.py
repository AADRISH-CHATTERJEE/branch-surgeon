"""Company Standards panel summary derived from organization rules."""

from __future__ import annotations

from refactory.organization.standards_summary import (
    merge_standards_with_org_rules,
    summarize_org_rule_policies,
)


def test_summarize_maps_default_org_rule_types():
    rows = [
        {
            "name": "Branch naming",
            "enabled": True,
            "rule_type": "branch_naming",
            "category": "branch_naming",
            "blocking": False,
            "conditions": [
                {
                    "field": "branch_name",
                    "operator": "matches",
                    "pattern": r"^(feature|bugfix)/.+",
                }
            ],
            "message": "Branch pattern required",
        },
        {
            "name": "Conventional Commits",
            "enabled": True,
            "rule_type": "commit_message",
            "category": "commit_message",
            "blocking": False,
            "conditions": [
                {
                    "field": "commit_message",
                    "operator": "matches",
                    "pattern": r"^feat:",
                }
            ],
            "message": "Use conventional commits",
        },
        {
            "name": "Controllers cannot call repositories",
            "enabled": True,
            "rule_type": "architecture",
            "category": "architecture_layer",
            "blocking": True,
            "conditions": [{"field": "imports", "operator": "matches", "pattern": "x"}],
            "message": "No controller→repo",
        },
        {
            "name": "Require tests",
            "enabled": True,
            "rule_type": "testing",
            "category": "required_tests",
            "blocking": True,
            "conditions": [],
            "message": "Need tests",
        },
        {
            "name": "Disabled branch",
            "enabled": False,
            "rule_type": "branch_naming",
            "blocking": True,
            "conditions": [],
        },
    ]
    summary = summarize_org_rule_policies(rows)
    assert summary["branch"]["configured"] is True
    assert summary["branch"]["pattern"]
    assert "Branch naming" in summary["branch"]["rule_names"]
    assert "Disabled branch" not in summary["branch"]["rule_names"]
    assert summary["commit"]["configured"] is True
    assert summary["architecture"]["configured"] is True
    assert summary["architecture"]["blocking"] is True
    assert summary["testing"]["require_tests"] is True
    assert summary["branch_policy"] is summary["branch"]
    assert summary["commit_policy"] is summary["commit"]


def test_merge_prefers_company_yaml_and_fills_gaps():
    company = {
        "organization_name": "Acme",
        "branch": {"pattern": r"^main$", "block": True},
        "commit": None,
        "architecture": None,
        "testing": None,
    }
    org = [
        {
            "name": "Org commits",
            "enabled": True,
            "rule_type": "commit_message",
            "blocking": False,
            "conditions": [
                {"field": "commit_message", "operator": "matches", "pattern": r"^fix:"}
            ],
            "message": "fix: required",
        },
        {
            "name": "Org arch",
            "enabled": True,
            "rule_type": "architecture",
            "blocking": True,
            "conditions": [],
        },
    ]
    merged = merge_standards_with_org_rules(company, org)
    # YAML branch kept
    assert merged["branch"]["pattern"] == r"^main$"
    # Gaps filled from org
    assert merged["commit"]["configured"] is True
    assert merged["architecture"]["configured"] is True
    assert merged["commit_policy"]["configured"] is True
    assert "organization_rules" in merged["standards_source"]
    assert "company.yaml" in merged["standards_source"]


def test_merge_all_from_org_when_no_yaml():
    merged = merge_standards_with_org_rules(
        {"organization_name": "default"},
        [
            {
                "name": "Branch",
                "enabled": True,
                "rule_type": "branch_naming",
                "blocking": False,
                "conditions": [
                    {
                        "field": "branch_name",
                        "operator": "matches",
                        "pattern": r"^feature/.+",
                    }
                ],
            }
        ],
    )
    assert merged["branch"]["configured"] is True
    assert merged["standards_source"] == "organization_rules"
