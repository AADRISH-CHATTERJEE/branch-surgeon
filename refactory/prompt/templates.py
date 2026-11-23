"""Local default prompt templates (versioned, configurable)."""

from __future__ import annotations

from refactory.backend.models import ReviewPrompt

PROMPT_TEMPLATE_VERSION = "2.1.0"

DEFAULT_SYSTEM_INSTRUCTIONS = (
    "You are a senior code reviewer for Refactory.\n"
    "Review only the provided context. Do not invent files, symbols, or APIs.\n"
    "Prioritize correctness, security, and maintainability.\n"
    "Be concise and actionable. Prefer specific findings over general advice.\n"
    "Respond with the Expected JSON Output schema only — no prose outside JSON.\n"
    "IMPORTANT: Every finding MUST include ALL fields shown in the schema.\n"
    "Every finding MUST have a numeric confidence (0.0–1.0) and a non-empty estimated_impact string."
)

DEFAULT_REVIEW_INSTRUCTIONS = (
    "- Prefer clear names and small functions.\n"
    "- Avoid silent exception swallowing.\n"
    "- Validate untrusted input at boundaries.\n"
    "- Do not introduce secrets into source or logs.\n"
    "- Keep changes minimal and reviewable.\n"
    "- Flag missing tests only when risk is medium or higher."
)

DEFAULT_EXPECTED_JSON = (
    "ALL fields below are REQUIRED for every finding. Do NOT omit any field.\n"
    "{\n"
    '  "summary": "short overall assessment",\n'
    '  "risk_level": "low|medium|high|critical",\n'
    '  "confidence": 0.85,\n'
    '  "findings": [\n'
    "    {\n"
    '      "title": "short title (REQUIRED)",\n'
    '      "severity": "info|low|medium|high|critical (REQUIRED)",\n'
    '      "category": "security|performance|correctness|maintainability|tests|style|other (REQUIRED)",\n'
    '      "file": "path/to/file (REQUIRED)",\n'
    '      "line": 42,\n'
    '      "explanation": "what is wrong and why it matters (REQUIRED)",\n'
    '      "recommendation": "how to fix, with code suggestion if applicable (REQUIRED)",\n'
    '      "confidence": 0.85,\n'
    '      "estimated_impact": "Security|Correctness|Performance|Maintainability|Reliability (REQUIRED)"\n'
    "    }\n"
    "  ]\n"
    "}"
)

# Backward-compatible aliases used by older imports/tests.
DEFAULT_CODING_STANDARDS = DEFAULT_REVIEW_INSTRUCTIONS
DEFAULT_OUTPUT_FORMAT = (
    "Respond with JSON matching Expected JSON Output:\n"
    "- summary: short overall assessment\n"
    "- risk_level: one of low | medium | high | critical\n"
    "- findings: list of {title, severity, category, file, line, explanation,\n"
    "  recommendation, confidence, estimated_impact}\n"
    "- confidence: number between 0 and 1"
)

DEFAULT_REVIEW_PROMPT = ReviewPrompt(
    name="review",
    version=PROMPT_TEMPLATE_VERSION,
    description="Local fallback review system prompt when the control plane is unavailable.",
    template=DEFAULT_SYSTEM_INSTRUCTIONS,
    variables=[],
    metadata={"source": "local_default", "prompt_version": PROMPT_TEMPLATE_VERSION},
)

# Canonical user-prompt section order (v2 compact layout).
# Company documentation is inserted after repository when present (see PromptBuilder).
SECTION_ORDER: tuple[str, ...] = (
    "repository",
    "pr_summary",
    "changed_files",
    "diff",
    "relevant_code",
    "dependency_impact",
    "review_instructions",
    "expected_json_output",
)

# Legacy keys remapped for older templates / tests.
LEGACY_SECTION_ALIASES: dict[str, str] = {
    "repository_summary": "repository",
    "pull_request_metadata": "pr_summary",
    "retrieved_context": "relevant_code",
    "related_files": "relevant_code",
    "impact_analysis": "dependency_impact",
    "coding_standards": "review_instructions",
    "required_output_format": "expected_json_output",
}

SECTION_TITLES: dict[str, str] = {
    "system_instructions": "SYSTEM",
    "repository": "Repository",
    "company_documentation": "Company Documentation",
    "pr_summary": "PR Summary",
    "changed_files": "Changed Files",
    "diff": "Git Diff",
    "relevant_code": "Relevant Code",
    "dependency_impact": "Dependency Impact",
    "review_instructions": "Review Instructions",
    "expected_json_output": "Expected JSON Output",
    # Legacy titles (still rendered if old keys appear)
    "repository_summary": "Repository",
    "pull_request_metadata": "PR Summary",
    "retrieved_context": "Relevant Code",
    "related_files": "Relevant Code",
    "impact_analysis": "Dependency Impact",
    "coding_standards": "Review Instructions",
    "required_output_format": "Expected JSON Output",
}

SECTION_SEPARATOR = "===================="
