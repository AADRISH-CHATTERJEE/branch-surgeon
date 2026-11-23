"""Seed default company documentation under .refactory/ when missing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from refactory.company.defaults import DEFAULT_DOCUMENTATION_MD, DOC_FILES
from refactory.company.loader import clear_company_doc_cache
from refactory.company.models import CompanyDocumentation


@dataclass
class DocumentationSeedResult:
    """Outcome of ensuring default documentation files exist."""

    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    seeded: bool = False

    @property
    def created_any(self) -> bool:
        return bool(self.created)


def documentation_paths(repo_root: Path) -> dict[str, Path]:
    """Map API field name → absolute Markdown path."""
    refactory = Path(repo_root) / ".refactory"
    return {
        field: refactory / filename
        for filename, field in DOC_FILES.items()
    }


def ensure_default_documentation(repo_root: Path) -> DocumentationSeedResult:
    """Create missing default documentation files; never overwrite existing ones.

    Returns which relative paths were created vs skipped. Clears the in-memory
    documentation cache when any file is written so the next load sees them.
    """
    root = Path(repo_root).resolve()
    refactory = root / ".refactory"
    result = DocumentationSeedResult()

    for filename, content in DEFAULT_DOCUMENTATION_MD.items():
        path = refactory / filename
        rel = f".refactory/{filename}"
        if path.is_file():
            result.skipped.append(rel)
            continue
        refactory.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        result.created.append(rel)

    result.seeded = result.created_any
    # Always drop caches after ensure so a prior empty load cannot hide
    # files that appeared on disk between requests (or via another process).
    clear_company_doc_cache()
    return result


def write_documentation(
    repo_root: Path,
    docs: CompanyDocumentation,
    *,
    fields: set[str] | None = None,
) -> list[str]:
    """Write documentation Markdown files (overwrite). Returns relative paths written.

    When ``fields`` is set, only those API field names are written.
    """
    root = Path(repo_root).resolve()
    refactory = root / ".refactory"
    refactory.mkdir(parents=True, exist_ok=True)

    payloads = {
        "architecture": docs.architecture,
        "coding_guidelines": docs.coding_guidelines,
        "security_guidelines": docs.security_guidelines,
        "testing_guidelines": docs.testing_guidelines,
    }
    selected = fields or set(payloads)
    written: list[str] = []
    for filename, field in DOC_FILES.items():
        if field not in selected:
            continue
        path = refactory / filename
        path.write_text(payloads[field], encoding="utf-8")
        written.append(f".refactory/{filename}")

    if written:
        clear_company_doc_cache()
    return written
