"""Preview engine — generates transformation previews for CLI display."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from refactory.transformation.models import (
    TransformationPatch,
    TransformationPlan,
    TransformationPreview,
    TransformationValidation,
)
from refactory.transformation.patch import PatchGenerator

if TYPE_CHECKING:
    from loguru import Logger


class PreviewEngine:
    """Generates human-readable previews of transformations."""

    def __init__(self, logger: "Logger") -> None:
        self._logger = logger
        self._patch_gen = PatchGenerator()

    def generate_preview(
        self,
        plan: TransformationPlan,
        patch: TransformationPatch,
        validation: TransformationValidation,
    ) -> TransformationPreview:
        """Generate a preview for a transformation."""
        modules: list[str] = []
        for f in patch.files_modified:
            parts = Path(f).parts
            if parts:
                modules.append(parts[0])
        modules = list(set(modules))

        symbols: list[str] = []
        for step in plan.steps:
            if step.description:
                symbols.append(step.description)

        stats = self._patch_gen.compute_statistics(patch)

        base_confidence = plan.estimated_confidence or (
            0.9 if validation.status.value == "passed" else 0.6
        )
        if validation.status.value != "passed" and base_confidence > 0.6:
            base_confidence = min(base_confidence, 0.6)

        symbols_out = list(plan.affected_symbols) or symbols[:10]

        return TransformationPreview(
            plan_id=plan.id,
            patch_id=patch.id,
            description=plan.description,
            goal=plan.goal or plan.description,
            operations=list(plan.operations),
            files_modified=patch.files_modified or list(plan.affected_files),
            additions=patch.additions,
            deletions=patch.deletions,
            modified_symbols=symbols_out[:20],
            risk=plan.estimated_risk,
            affected_modules=modules,
            confidence=float(base_confidence),
            estimated_review_time=stats.estimated_review_time,
            diff_preview=patch.diff_content[:2000],
            rollback_available=True,
            validation=validation,
            plan=plan,
        )

    def format_preview(self, preview: TransformationPreview) -> str:
        """Format preview for CLI display."""
        lines = [
            "", "Transformation Preview", "=====================", "",
            f"Plan: {preview.plan_id}",
            f"Risk: {preview.risk.upper()}",
            f"Confidence: {preview.confidence:.0%}",
            f"Review Time: {preview.estimated_review_time}", "",
            f"Files Modified: {len(preview.files_modified)}",
            f"  +{preview.additions} / -{preview.deletions}", "",
        ]
        if preview.files_modified:
            lines.append("Files:")
            for f in preview.files_modified:
                lines.append(f"  {f}")
            lines.append("")

        if preview.modified_symbols:
            lines.append("Changes:")
            for s in preview.modified_symbols:
                lines.append(f"  • {s}")
            lines.append("")

        if preview.affected_modules:
            lines.append(f"Modules: {', '.join(preview.affected_modules)}")
            lines.append("")

        lines.append(f"Validation: {preview.validation.status.value.upper()}")
        if preview.validation.errors:
            for e in preview.validation.errors:
                lines.append(f"  ✗ {e}")
        if preview.validation.warnings:
            for w in preview.validation.warnings:
                lines.append(f"  ⚠ {w}")
        lines.append("")

        if preview.diff_preview:
            lines.append("Diff:")
            lines.append(preview.diff_preview[:1000])
            lines.append("")

        return "\n".join(lines)
