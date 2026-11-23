"""ArchitecturePolicyService — enforces architectural layer constraints.

Detects violations like controllers accessing databases directly,
services depending on UI, or circular dependencies between layers.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from refactory.policies.models import (
    ArchitectureLayer,
    ArchitecturePolicy,
    PolicyReport,
    PolicyViolation,
    ViolationType,
)

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.parser.service import ParserService


class ArchitecturePolicyService:
    """Evaluates architecture policies against a repository."""

    def __init__(
        self,
        logger: "Logger",
        parser_service: "ParserService",
    ) -> None:
        self._logger = logger
        self._parser = parser_service
        self._policy: ArchitecturePolicy | None = None

    def load_policy(self, policy: ArchitecturePolicy) -> None:
        """Set the active architecture policy."""
        self._policy = policy
        self._logger.info("Loaded architecture policy: {}", policy.name)

    def load_policy_from_config(self, config: dict[str, Any]) -> None:
        """Load policy from configuration dict."""
        layers = []
        for layer_data in config.get("layers", []):
            layers.append(ArchitectureLayer(
                name=layer_data["name"],
                patterns=layer_data.get("patterns", []),
                allowed_dependencies=layer_data.get("allowed_dependencies", []),
                description=layer_data.get("description", ""),
            ))
        policy = ArchitecturePolicy(
            name=config.get("name", "custom"),
            description=config.get("description", ""),
            layers=layers,
        )
        self.load_policy(policy)

    @property
    def policy(self) -> ArchitecturePolicy | None:
        return self._policy

    def evaluate(
        self,
        file_imports: dict[str, list[str]],
    ) -> PolicyReport:
        """Evaluate architecture policy against file imports.

        Args:
            file_imports: Mapping of file paths to their import targets.
        """
        if self._policy is None:
            return PolicyReport(passed=True)

        violations: list[PolicyViolation] = []
        files_checked = 0

        layer_map = self._build_layer_map()

        for source_file, imports in file_imports.items():
            files_checked += 1
            source_layer = self._resolve_layer(source_file, layer_map)
            if not source_layer:
                continue

            allowed = self._get_allowed_deps(source_layer)
            for imp in imports:
                target_layer = self._resolve_layer(imp, layer_map)
                if not target_layer or target_layer == source_layer:
                    continue
                if target_layer not in allowed and allowed:
                    violations.append(PolicyViolation(
                        violation_type=ViolationType.LAYER_VIOLATION,
                        source_file=source_file,
                        target_file=imp,
                        source_layer=source_layer,
                        target_layer=target_layer,
                        description=(
                            f"'{source_layer}' layer cannot depend on '{target_layer}' layer"
                        ),
                    ))

        self._logger.info(
            "Architecture policy: {} violations across {} files",
            len(violations), files_checked,
        )
        return PolicyReport(
            violations=violations,
            layers_checked=len(self._policy.layers),
            files_checked=files_checked,
            passed=len(violations) == 0,
        )

    def _build_layer_map(self) -> dict[str, str]:
        """Build pattern -> layer name mapping."""
        layer_map: dict[str, str] = {}
        if self._policy:
            for layer in self._policy.layers:
                for pattern in layer.patterns:
                    layer_map[pattern] = layer.name
        return layer_map

    def _resolve_layer(self, file_path: str, layer_map: dict[str, str]) -> str:
        """Resolve which layer a file belongs to."""
        for pattern, layer_name in layer_map.items():
            if re.search(pattern, file_path):
                return layer_name
        return ""

    def _get_allowed_deps(self, layer_name: str) -> list[str]:
        """Get allowed dependencies for a layer."""
        if self._policy:
            for layer in self._policy.layers:
                if layer.name == layer_name:
                    return layer.allowed_dependencies
        return []
