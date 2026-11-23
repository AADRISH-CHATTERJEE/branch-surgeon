"""GET/PUT /documentation — company Markdown documents."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from refactory.api.deps import ContainerDep, RepoRootDep
from refactory.api.routes._activity import persist_repo_activity
from refactory.api.schemas import ApiResponse, ok
from refactory.api.serialize import to_data
from refactory.company.loader import load_company_documentation
from refactory.company.models import CompanyDocumentation
from refactory.company.seed import ensure_default_documentation, write_documentation

router = APIRouter(tags=["documentation"])


class DocumentationUpdateRequest(BaseModel):
    """Partial or full update of company documentation Markdown."""

    architecture: str | None = None
    coding_guidelines: str | None = None
    security_guidelines: str | None = None
    testing_guidelines: str | None = None


@router.get(
    "/documentation",
    response_model=ApiResponse,
    summary="Get company documentation Markdown",
    description=(
        "Returns the four company documentation sections. "
        "When no documentation files exist, seeds defaults under .refactory/ "
        "(never overwrites existing files) and records History: Documentation initialized."
    ),
)
def get_documentation(container: ContainerDep, repo_root: RepoRootDep) -> ApiResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    seed = ensure_default_documentation(root)
    if seed.created_any:
        persist_repo_activity(
            container,
            command="documentation",
            result_type="documentation_initialized",
            summary="Documentation initialized",
            result_data={
                "created": seed.created,
                "skipped": seed.skipped,
            },
        )
    docs = load_company_documentation(root)
    return ok(
        to_data(docs),
        meta={
            "repo_root": str(repo_root),
            "seeded": seed.seeded,
            "created": seed.created,
        },
    )


@router.put(
    "/documentation",
    response_model=ApiResponse,
    summary="Update company documentation Markdown",
    description=(
        "Writes provided sections to .refactory/*.md and records History: "
        "Documentation updated. Omitted fields are left unchanged."
    ),
)
def update_documentation(
    body: DocumentationUpdateRequest,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    current = load_company_documentation(root)
    fields: set[str] = set()
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return ok(
            to_data(current),
            message="No documentation fields provided",
            meta={"repo_root": str(repo_root), "updated": []},
        )

    data = current.model_dump()
    for key, value in updates.items():
        if value is None:
            continue
        data[key] = value
        fields.add(key)

    docs = CompanyDocumentation.model_validate(data)
    written = write_documentation(root, docs, fields=fields)
    persist_repo_activity(
        container,
        command="documentation",
        result_type="documentation_updated",
        summary="Documentation updated",
        result_data={"updated": written, "fields": sorted(fields)},
    )
    return ok(
        to_data(docs),
        message="Documentation updated",
        meta={"repo_root": str(repo_root), "updated": written},
    )


@router.post(
    "/documentation/seed",
    response_model=ApiResponse,
    summary="Seed default documentation when missing",
    description="Creates missing .refactory/*.md defaults without overwriting existing files.",
)
def seed_documentation(container: ContainerDep, repo_root: RepoRootDep) -> ApiResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    seed = ensure_default_documentation(root)
    if seed.created_any:
        persist_repo_activity(
            container,
            command="documentation",
            result_type="documentation_initialized",
            summary="Documentation initialized",
            result_data={
                "created": seed.created,
                "skipped": seed.skipped,
            },
        )
    docs = load_company_documentation(root)
    return ok(
        {
            "documentation": to_data(docs),
            "created": seed.created,
            "skipped": seed.skipped,
            "seeded": seed.seeded,
        },
        message="Documentation initialized" if seed.seeded else "Documentation already present",
        meta={"repo_root": str(repo_root)},
    )
