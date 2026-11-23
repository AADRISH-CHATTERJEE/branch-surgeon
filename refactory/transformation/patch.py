"""Patch generator — produces unified diff patches compatible with `git apply`."""

from __future__ import annotations

import difflib
from pathlib import Path

from refactory.transformation.models import (
    PatchHunk,
    PatchStatistics,
    TransformationPatch,
    TransformationPlan,
    TransformationStep,
)


class PatchGenerator:
    """Generates unified diff patches from transformation plans."""

    def generate(self, plan: TransformationPlan, root: Path) -> TransformationPatch:
        """Generate a unified diff patch from a transformation plan."""
        hunks: list[PatchHunk] = []
        all_diff_lines: list[str] = []
        additions = 0
        deletions = 0
        files_modified: list[str] = []

        for step in plan.steps:
            if not step.file_path:
                continue

            original = step.original_content
            new = step.new_content

            if not original and new:
                file_path = root / step.file_path
                if file_path.is_file():
                    try:
                        original = file_path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        original = ""

            if not new and not original:
                continue

            diff = self._generate_unified_diff(step.file_path, original, new)
            if diff:
                all_diff_lines.extend(diff)
                files_modified.append(step.file_path)
                hunk = PatchHunk(
                    file_path=step.file_path,
                    content="\n".join(diff),
                )
                hunks.append(hunk)
                additions += sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
                deletions += sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

        diff_content = "\n".join(all_diff_lines)

        return TransformationPatch(
            plan_id=plan.id,
            diff_content=diff_content,
            files_modified=files_modified,
            hunks=hunks,
            additions=additions,
            deletions=deletions,
        )

    def generate_from_content(
        self, file_path: str, original: str, new_content: str
    ) -> TransformationPatch:
        """Generate a patch from raw before/after content."""
        plan = TransformationPlan(
            steps=[TransformationStep(
                file_path=file_path,
                original_content=original,
                new_content=new_content,
            )]
        )
        return self.generate(plan, Path("."))

    def compute_statistics(self, patch: TransformationPatch) -> PatchStatistics:
        """Compute statistics for a patch."""
        review_minutes = max(1, (patch.additions + patch.deletions) // 20)
        return PatchStatistics(
            files_modified=len(patch.files_modified),
            lines_added=patch.additions,
            lines_removed=patch.deletions,
            hunks_count=len(patch.hunks),
            estimated_review_time=f"{review_minutes} min",
        )

    def generate_rollback(self, patch: TransformationPatch) -> str:
        """Generate a reverse patch for rollback."""
        if not patch.diff_content:
            return ""
        lines = patch.diff_content.split("\n")
        reversed_lines: list[str] = []
        for line in lines:
            if line.startswith("--- a/"):
                reversed_lines.append(line.replace("--- a/", "+++ b/"))
            elif line.startswith("+++ b/"):
                reversed_lines.append(line.replace("+++ b/", "--- a/"))
            elif line.startswith("+") and not line.startswith("+++"):
                reversed_lines.append("-" + line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                reversed_lines.append("+" + line[1:])
            else:
                reversed_lines.append(line)
        return "\n".join(reversed_lines)

    def _generate_unified_diff(
        self, file_path: str, original: str, new: str
    ) -> list[str]:
        """Generate unified diff lines for a single file."""
        if original == new:
            return []
        orig_lines = original.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            orig_lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        ))
        return [line.rstrip("\n") for line in diff]
