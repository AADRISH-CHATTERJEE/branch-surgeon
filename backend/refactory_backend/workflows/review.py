"""Static review workflow definition (control-plane content for CLI)."""

from __future__ import annotations

from refactory_backend.schemas.workflows import WorkflowDefinitionResponse, WorkflowStep

REVIEW_WORKFLOW = WorkflowDefinitionResponse(
    name="review",
    version="1.0.0",
    description="Default CLI review workflow orchestrated locally by ReviewEngine.",
    steps=[
        WorkflowStep(
            id="verify_git",
            name="Verify local Git repository",
            description="Ensure the working directory is a Git repository.",
        ),
        WorkflowStep(
            id="load_metadata",
            name="Load repository metadata",
            description="Read branch, remote, and repository identity.",
        ),
        WorkflowStep(
            id="fetch_pr",
            name="Fetch pull request",
            description="Load PR metadata from the configured Git host.",
        ),
        WorkflowStep(
            id="ensure_index",
            name="Ensure local index",
            description="Build or reuse the deterministic repository index.",
        ),
        WorkflowStep(
            id="retrieve_context",
            name="Retrieve related context",
            description="Semantic retrieval over local embeddings.",
        ),
        WorkflowStep(
            id="ai_review",
            name="Request AI review",
            description="Produce a structured review via the AI gateway (local/CLI).",
            optional=False,
        ),
    ],
    feature_flags={
        "use_remote_prompts": True,
        "telemetry_enabled": True,
        "incremental_index": True,
        "embeddings_required": True,
    },
    metadata={
        "execution_location": "cli",
        "control_plane_only": True,
    },
)


def get_review_workflow() -> WorkflowDefinitionResponse:
    return REVIEW_WORKFLOW
