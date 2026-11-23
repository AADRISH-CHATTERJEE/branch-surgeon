"""Load company standards and guideline documents from .refactory/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from refactory.company.models import (
    ArchitectureRuleConfig,
    BranchRuleConfig,
    CommitRuleConfig,
    CompanyDocumentation,
    CompanyGuidelines,
    CompanyStandards,
    ForbiddenDependency,
    TestingRuleConfig,
)

# Cached after first load per resolved repo root.
# Values: (signature of file mtimes/sizes, payload). Invalidated when files change.
_guidelines_cache: dict[str, tuple[str, CompanyGuidelines]] = {}
_documentation_cache: dict[str, tuple[str, CompanyDocumentation]] = {}


def _doc_files_signature(repo_root: Path) -> str:
    """Fingerprint the four company Markdown files for cache invalidation.

    Uses content hashes (files are small) so same-size rewrites and
    newly-created sibling files always bust a stale empty cache.
    """
    import hashlib

    refactory = Path(repo_root) / ".refactory"
    parts: list[str] = []
    for name in (
        "architecture.md",
        "coding_guidelines.md",
        "security_guidelines.md",
        "testing_guidelines.md",
    ):
        path = refactory / name
        if path.is_file():
            digest = hashlib.sha1(path.read_bytes()).hexdigest()[:12]
            parts.append(f"{name}:{digest}")
        else:
            parts.append(f"{name}:missing")
    return "|".join(parts)


def _read_yaml_or_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise ValueError("PyYAML is required to load company.yaml") from exc
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def load_company_standards(repo_root: Path) -> CompanyStandards:
    """Load .refactory/company.yaml or company.json (YAML preferred)."""
    refactory = repo_root / ".refactory"
    yaml_path = refactory / "company.yaml"
    json_path = refactory / "company.json"

    data: dict[str, Any] = {}
    if yaml_path.is_file():
        data = _read_yaml_or_json(yaml_path)
    elif json_path.is_file():
        data = _read_yaml_or_json(json_path)
    else:
        return CompanyStandards()

    return _parse_company_data(data)


def _parse_company_data(data: dict[str, Any]) -> CompanyStandards:
    """Parse both the simple Phase-8 schema and legacy nested shapes."""
    org = data.get("organization") or {}
    name = ""
    if isinstance(org, dict):
        name = str(org.get("name") or "")
    if not name:
        name = str(data.get("name") or "default")

    branch = _parse_branch(data)
    commit = _parse_commit(data)
    architecture = _parse_architecture(data)
    testing = _parse_testing(data)

    return CompanyStandards(
        organization_name=name,
        branch=branch,
        commit=commit,
        architecture=architecture,
        testing=testing,
        extras={
            k: v
            for k, v in data.items()
            if k
            not in {
                "organization",
                "name",
                "branch",
                "commit",
                "architecture",
                "testing",
                "standards",
                "branch_strategy",
                "commit_convention",
                "test_requirements",
            }
        },
    )


def _parse_branch(data: dict[str, Any]) -> BranchRuleConfig | None:
    raw = data.get("branch")
    if isinstance(raw, dict) and raw.get("pattern"):
        return BranchRuleConfig(
            pattern=str(raw["pattern"]),
            block=bool(raw.get("block", True)),
            message=str(raw.get("message") or ""),
        )
    # Legacy: branch_strategy.branch_pattern
    strat = data.get("branch_strategy")
    if isinstance(strat, dict) and strat.get("branch_pattern"):
        return BranchRuleConfig(
            pattern=str(strat["branch_pattern"]),
            block=True,
            message="",
        )
    return None


def _parse_commit(data: dict[str, Any]) -> CommitRuleConfig | None:
    raw = data.get("commit")
    if isinstance(raw, dict) and raw.get("pattern"):
        return CommitRuleConfig(
            pattern=str(raw["pattern"]),
            block=bool(raw.get("block", True)),
            message=str(raw.get("message") or ""),
        )
    conv = data.get("commit_convention")
    if isinstance(conv, dict) and conv.get("pattern"):
        return CommitRuleConfig(
            pattern=str(conv["pattern"]),
            block=True,
            message="",
        )
    return None


def _parse_architecture(data: dict[str, Any]) -> ArchitectureRuleConfig | None:
    raw = data.get("architecture")
    if not isinstance(raw, dict):
        return None
    deps_raw = raw.get("forbidden_dependencies") or []
    deps: list[ForbiddenDependency] = []
    if isinstance(deps_raw, list):
        for item in deps_raw:
            if not isinstance(item, dict):
                continue
            deps.append(
                ForbiddenDependency(
                    **{
                        "from": str(item.get("from") or item.get("from_layer") or ""),
                        "to": str(item.get("to") or item.get("to_layer") or ""),
                        "message": str(item.get("message") or ""),
                    }
                )
            )
    if not deps:
        return None
    return ArchitectureRuleConfig(
        forbidden_dependencies=deps,
        block=bool(raw.get("block", True)),
    )


def _parse_testing(data: dict[str, Any]) -> TestingRuleConfig | None:
    raw = data.get("testing")
    if isinstance(raw, dict):
        return TestingRuleConfig(
            require_tests=bool(raw.get("require_tests", False)),
            block=bool(raw.get("block", False)),
            test_path_pattern=str(
                raw.get("test_path_pattern")
                or r"(^|/)tests?/|(^|/)test_[^/]+\.py$|_test\.py$"
            ),
            message=str(raw.get("message") or ""),
        )
    # Legacy
    tr = data.get("test_requirements")
    if isinstance(tr, dict) and tr.get("require_unit_tests"):
        return TestingRuleConfig(require_tests=True, block=False)
    return None


def load_company_guidelines(repo_root: Path) -> CompanyGuidelines:
    """Load optional markdown guideline documents from .refactory/.

    Missing files yield empty strings. Results are cached per repository root
    and automatically invalidated when any of the four Markdown files change
    (mtime/size), so newly seeded sections appear without an API restart.
    """
    root = Path(repo_root).resolve()
    key = str(root)
    signature = _doc_files_signature(root)
    cached = _guidelines_cache.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]

    refactory = root / ".refactory"
    guidelines = CompanyGuidelines(
        architecture_md=_read_optional_text(refactory / "architecture.md"),
        coding_guidelines_md=_read_optional_text(refactory / "coding_guidelines.md"),
        security_guidelines_md=_read_optional_text(refactory / "security_guidelines.md"),
        testing_guidelines_md=_read_optional_text(refactory / "testing_guidelines.md"),
    )
    _guidelines_cache[key] = (signature, guidelines)
    return guidelines


def load_company_documentation(repo_root: Path) -> CompanyDocumentation:
    """Load company documentation for AI prompt context.

    Same files as :func:`load_company_guidelines`, returned as
    :class:`CompanyDocumentation`. Cache shares the file-signature invalidation.
    """
    root = Path(repo_root).resolve()
    key = str(root)
    signature = _doc_files_signature(root)
    cached = _documentation_cache.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]

    docs = load_company_guidelines(repo_root).to_documentation()
    # Keep documentation cache signature in sync even if guidelines was a hit
    # with a different prior signature edge-case during concurrent updates.
    signature = _doc_files_signature(root)
    _documentation_cache[key] = (signature, docs)
    return docs


def clear_company_doc_cache() -> None:
    """Clear documentation/guidelines caches (tests / forced reload)."""
    _guidelines_cache.clear()
    _documentation_cache.clear()


def _read_optional_text(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def load_architecture_yaml(repo_root: Path) -> dict[str, Any] | None:
    """Load .refactory/architecture.yaml if present (layers + policies)."""
    path = repo_root / ".refactory" / "architecture.yaml"
    if not path.is_file():
        return None
    return _read_yaml_or_json(path)


def architecture_config_for_service(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert architecture.yaml into ArchitecturePolicyService config shape.

    Supports:
    - layers with allowed_dependencies (native)
    - layers + policies: [{from, to, action: deny}] (init template)
    """
    layers_in = raw.get("layers") or []
    if not isinstance(layers_in, list):
        return {"name": raw.get("name", "custom"), "layers": []}

    layer_names = [
        str(layer.get("name"))
        for layer in layers_in
        if isinstance(layer, dict) and layer.get("name")
    ]

    # Start from explicit allowed_dependencies when present
    layers_out: list[dict[str, Any]] = []
    for layer in layers_in:
        if not isinstance(layer, dict) or not layer.get("name"):
            continue
        allowed = list(layer.get("allowed_dependencies") or [])
        layers_out.append(
            {
                "name": str(layer["name"]),
                "patterns": list(layer.get("patterns") or []),
                "allowed_dependencies": allowed,
                "description": str(layer.get("description") or ""),
            }
        )

    policies = raw.get("policies") or []
    if isinstance(policies, list) and policies:
        # Convert deny edges into allowed_dependencies (all other layers)
        deny: dict[str, set[str]] = {n: set() for n in layer_names}
        for pol in policies:
            if not isinstance(pol, dict):
                continue
            if str(pol.get("action", "deny")).lower() != "deny":
                continue
            src = str(pol.get("from") or "")
            dst = str(pol.get("to") or "")
            if src in deny and dst:
                deny[src].add(dst)
        for layer in layers_out:
            name = layer["name"]
            if layer["allowed_dependencies"]:
                continue
            # Default allow: all other layers minus denied
            layer["allowed_dependencies"] = [
                n for n in layer_names if n != name and n not in deny.get(name, set())
            ]

    return {"name": str(raw.get("name") or "custom"), "layers": layers_out}
