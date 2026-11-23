"""Prompt template schemas (static control-plane content)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PromptTemplateResponse(BaseModel):
    name: str
    version: str
    description: str
    template: str
    variables: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
