"""GitHub-facing data contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChangedFile(BaseModel):
    path: str
    status: str = "modified"
    additions: int = 0
    deletions: int = 0
    patch: str | None = None


class PullRequest(BaseModel):
    number: int
    title: str
    body: str = ""
    state: str = "open"
    author: str | None = None
    base_branch: str | None = None
    head_branch: str | None = None
    html_url: str | None = None
    changed_files: list[ChangedFile] = Field(default_factory=list)
    diff: str = ""
