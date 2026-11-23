"""Workflow definition schemas (static control-plane content)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WorkflowStep(BaseModel):
    id: str
    name: str
    description: str
    optional: bool = False


class WorkflowDefinitionResponse(BaseModel):
    name: str
    version: str
    description: str
    steps: list[WorkflowStep]
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
