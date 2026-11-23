"""Configurable prompt templates for AI features.

Prompts are stored separately and can be customized by administrators.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PromptTemplate(BaseModel):
    """A single prompt template."""

    name: str
    category: str = "general"
    system_prompt: str = ""
    user_prompt_template: str = ""
    max_tokens: int = 500
    temperature: float = 0.3
    description: str = ""
    version: str = "1.0"


class PromptRegistry(BaseModel):
    """Collection of prompt templates."""

    templates: dict[str, PromptTemplate] = Field(default_factory=dict)


_DEFAULT_TEMPLATES: dict[str, PromptTemplate] = {
    "review": PromptTemplate(
        name="review",
        category="review",
        system_prompt=(
            "You are a senior code reviewer. Review the code changes and provide "
            "constructive feedback focusing on bugs, performance, security, and maintainability."
        ),
        user_prompt_template="Review the following changes:\n{context}",
        max_tokens=800,
        description="Code review prompt",
    ),
    "architecture": PromptTemplate(
        name="architecture",
        category="architecture",
        system_prompt=(
            "You are a software architect. Analyze the codebase architecture and identify "
            "patterns, violations, and improvement opportunities."
        ),
        user_prompt_template="Analyze the architecture:\n{context}",
        max_tokens=600,
        description="Architecture analysis prompt",
    ),
    "documentation": PromptTemplate(
        name="documentation",
        category="documentation",
        system_prompt=(
            "You are a technical writer. Generate clear, concise documentation "
            "for the given code."
        ),
        user_prompt_template="Document the following:\n{context}",
        max_tokens=500,
        description="Documentation generation prompt",
    ),
    "patch": PromptTemplate(
        name="patch",
        category="patch",
        system_prompt=(
            "You are a code refactoring expert. Generate minimal, correct patches "
            "that fix the identified issues."
        ),
        user_prompt_template="Generate a patch for:\n{context}",
        max_tokens=1000,
        description="Patch generation prompt",
    ),
    "recommendation_patch": PromptTemplate(
        name="recommendation_patch",
        category="patch",
        version="1.0.0",
        system_prompt=(
            "You are a code refactoring expert. Generate minimal, correct "
            "file modifications that address the recommendation. "
            "Never invent repository files that were not provided. "
            "Return JSON only."
        ),
        user_prompt_template="Generate a patch for:\n{context}",
        max_tokens=4000,
        temperature=0.2,
        description="Recommendation → AI patch (structured JSON)",
    ),
    "test_generation": PromptTemplate(
        name="test_generation",
        category="testing",
        system_prompt=(
            "You are a test engineering expert. Generate comprehensive unit tests "
            "that cover edge cases and error paths."
        ),
        user_prompt_template="Generate tests for:\n{context}",
        max_tokens=1000,
        description="Test generation prompt",
    ),
    "pr_summary": PromptTemplate(
        name="pr_summary",
        category="pr",
        system_prompt=(
            "Generate a concise PR summary. Include: overview, key changes, and impact."
        ),
        user_prompt_template="Summarize this PR:\n{context}",
        max_tokens=500,
        description="PR summary prompt",
    ),
    "explain_change": PromptTemplate(
        name="explain_change",
        category="explanation",
        system_prompt=(
            "Explain why this code change matters. Cover: purpose, downstream effects, "
            "migration concerns, and architectural consequences. Be concise."
        ),
        user_prompt_template="{context}",
        max_tokens=500,
        description="Change explanation prompt",
    ),
    "security_review": PromptTemplate(
        name="security_review",
        category="security",
        system_prompt=(
            "You are a security engineer. Identify security vulnerabilities, "
            "insecure patterns, and recommend fixes."
        ),
        user_prompt_template="Security review:\n{context}",
        max_tokens=600,
        description="Security review prompt",
    ),
}


class PromptTemplateService:
    """Manages prompt templates with configurable overrides."""

    def __init__(self) -> None:
        self._templates: dict[str, PromptTemplate] = dict(_DEFAULT_TEMPLATES)

    def get(self, name: str) -> PromptTemplate | None:
        """Get a prompt template by name."""
        return self._templates.get(name)

    def register(self, template: PromptTemplate) -> None:
        """Register or override a prompt template."""
        self._templates[template.name] = template

    def list_templates(self) -> list[PromptTemplate]:
        """List all available templates."""
        return list(self._templates.values())

    def load_from_file(self, path: Path) -> int:
        """Load custom templates from a JSON file."""
        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
            count = 0
            for name, tmpl_data in data.get("templates", {}).items():
                self._templates[name] = PromptTemplate(name=name, **tmpl_data)
                count += 1
            return count
        except Exception:  # noqa: BLE001
            return 0

    def load_from_repo(self, repo_root: Path) -> int:
        """Load templates from .refactory/prompts.json."""
        prompts_path = repo_root / ".refactory" / "prompts.json"
        if prompts_path.is_file():
            return self.load_from_file(prompts_path)
        return 0

    def render(self, name: str, **kwargs: Any) -> tuple[str, str]:
        """Render a template with variables. Returns (system_prompt, user_prompt)."""
        template = self.get(name)
        if template is None:
            return "", ""
        user_prompt = template.user_prompt_template.format(**kwargs) if kwargs else template.user_prompt_template
        return template.system_prompt, user_prompt

    @property
    def categories(self) -> list[str]:
        """Get unique categories."""
        return sorted(set(t.category for t in self._templates.values()))
