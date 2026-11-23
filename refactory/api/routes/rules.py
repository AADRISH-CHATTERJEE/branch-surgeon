"""POST /rules/check and GET /rules — company + organization rules presentation."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Header

from refactory.api.deps import ContainerDep, RepoRootDep
from refactory.api.schemas import ApiResponse, RulesCheckRequest, ok
from refactory.api.serialize import to_data
from refactory.company.context import resolve_gate_context

router = APIRouter(prefix="/rules", tags=["rules"])


@router.post(
    "/check",
    response_model=ApiResponse,
    summary="Run company rules check",
    description=(
        "Evaluates company.yaml + rules.yaml + organization rules via "
        "CompanyRulesChecker. Returns PASS / WARN / BLOCK without running AI review."
    ),
)
def rules_check(
    body: RulesCheckRequest,
    container: ContainerDep,
    repo_root: RepoRootDep,
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_team_id: str | None = Header(default=None, alias="X-Team-Id"),
) -> ApiResponse:
    git = container.git_service
    root = Path(git.get_root_path()).resolve()
    ctx = resolve_gate_context(
        git,
        branch_name=body.branch,
        commit_message=body.commit,
        base_branch=body.base,
        changed_files=body.changed_files,
    )
    if x_org_id or x_team_id:
        container.company_rules_checker.set_rule_scope(
            organization_id=x_org_id, team_id=x_team_id
        )
    result = container.company_rules_checker.check(
        root,
        branch_name=ctx.branch_name,
        commit_message=ctx.commit_message,
        commit_messages=ctx.commit_messages,
        changed_files=ctx.changed_files,
        organization_id=x_org_id,
        team_id=x_team_id,
    )
    payload = {
        "outcome": result.outcome.value,
        "violations": [v.model_dump() for v in result.violations],
        "blocker_count": len(result.blockers),
        "warning_count": len(result.warnings),
        "summary": result.summary_text(),
        "context": ctx.model_dump(),
    }
    # Persist activity (mirrors CLI / review gate)
    try:
        repo = container.query_service.get_repository_by_root(str(root))
        if repo is not None:
            container.persistence_service.persist_analysis_run(
                repository_id=repo["id"],
                command="rules-check",
                result_type="company_rules",
                status=result.outcome.value,
                branch=ctx.branch_name or None,
                result_data={
                    "outcome": result.outcome.value,
                    "violations": payload["violations"],
                    "blocker_count": payload["blocker_count"],
                    "warning_count": payload["warning_count"],
                    "summary": payload["summary"],
                },
            )
    except Exception:  # noqa: BLE001
        pass

    return ok(
        payload,
        message=f"Rules check: {result.outcome.value}",
        meta={"repo_root": str(repo_root)},
    )


@router.get(
    "",
    response_model=ApiResponse,
    summary="Inspect loaded company standards and rules",
    description=(
        "Returns company standards (company.yaml, with gaps filled from enabled "
        "organization rules), built-in rules.yaml catalog, and organization rules."
    ),
)
def list_rules(container: ContainerDep, repo_root: RepoRootDep) -> ApiResponse:
    from refactory.company.loader import load_company_standards
    from refactory.organization.standards_summary import merge_standards_with_org_rules

    root = Path(container.git_service.get_root_path()).resolve()
    standards = load_company_standards(root)
    # Load rules.yaml into the engine for inspection (does not mutate review flow).
    engine = container.rule_engine
    rules_error = None
    try:
        engine.clear_rules()
        count = engine.load_rules(root)
    except ValueError as exc:
        count = 0
        rules_error = str(exc)

    builtin_rules = [
        {
            "name": r.name,
            "category": getattr(r.category, "value", str(r.category)),
            "severity": getattr(r.severity, "value", str(r.severity)),
            "blocking": bool(getattr(r, "blocking", False)),
            "message": getattr(r, "message", "") or "",
            "description": getattr(r, "description", "") or "",
            "enabled": bool(getattr(r, "enabled", True)),
            "source": "builtin",
            "rule_type": getattr(r, "rule_type", "") or getattr(r.category, "value", ""),
            "documentation_url": getattr(r, "documentation_url", "") or "",
            "conditions": [c.model_dump() for c in getattr(r, "conditions", []) or []],
        }
        for r in engine.rules
    ]
    org_rules = container.organization_rule_service.list_rules()
    # Pass through the service DTO so ``blocking`` (and other fields) stay consistent
    # with GET /organization-rules. Always coerce blocking to a concrete bool.
    org_for_catalog = [
        {
            **r,
            "source": r.get("source") or "organization",
            "blocking": bool(r.get("blocking", False)),
        }
        for r in org_rules
    ]
    # Prefer company.yaml; fill missing branch/commit/architecture/testing from
    # enabled organization rules so the Company Standards panel is populated.
    standards_payload = merge_standards_with_org_rules(
        to_data(standards) or {},
        org_for_catalog,
    )

    data = {
        "standards": standards_payload,
        "rules": builtin_rules,
        "builtin_rules": builtin_rules,
        "organization_rules": org_for_catalog,
        "rule_count": count,
        "organization_rule_count": len(org_for_catalog),
    }
    if rules_error:
        data["rules_error"] = rules_error
    return ok(
        data,
        message="Standards loaded; rules.yaml invalid" if rules_error else "",
        meta={"repo_root": str(repo_root)},
    )
