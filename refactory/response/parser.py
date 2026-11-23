"""Best-effort parser: raw AI review text → ReviewResult / PartialReviewResult.

Does not call AI providers. Never raises for malformed model output.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from refactory.core.logger import bind_context, logging_operation
from refactory.response.json_repair import try_parse_json
from refactory.response.models import (
    PartialReviewResult,
    ParsedReview,
    ReviewMetadata,
    ReviewResult,
    ReviewSuggestion,
)
from refactory.response.schema import validate_review_document

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.ai.models import AIResponse

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_KV_RE = re.compile(
    r"^(?:\*\*|__)?(?P<key>[A-Za-z][\w\s/-]*?)(?:\*\*|__)?\s*[:=]\s*(?P<value>.*)$"
)
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_CONFIDENCE_INLINE_RE = re.compile(
    r"confidence\s*[:=]\s*([0-9]*\.?[0-9]+%?)",
    re.IGNORECASE,
)

_RISK_ALIASES = frozenset(
    {"risk", "risk_level", "overall_risk", "severity"}
)
_SUMMARY_ALIASES = frozenset({"summary", "overview", "assessment"})
_CONFIDENCE_ALIASES = frozenset({"confidence", "score"})
_FINDINGS_ALIASES = frozenset(
    {"findings", "suggestions", "issues", "recommendations", "review_findings"}
)
_SUGGESTION_FIELD_ALIASES: dict[str, str] = {
    "file": "file",
    "file_path": "file",
    "path": "file",
    "filename": "file",
    "line": "line",
    "line_number": "line",
    "lineno": "line",
    "severity": "severity",
    "level": "severity",
    "title": "title",
    "name": "title",
    "explanation": "explanation",
    "detail": "explanation",
    "details": "explanation",
    "description": "explanation",
    "recommendation": "recommendation",
    "fix": "recommendation",
    "suggestion": "recommendation",
    "code": "code_snippet",
    "code_snippet": "code_snippet",
    "snippet": "code_snippet",
    "category": "category",
    "type": "category",
    "kind": "category",
    "confidence": "confidence",
    "estimated_impact": "estimated_impact",
    "impact": "estimated_impact",
    "estimated impact": "estimated_impact",
}
_VALID_RISKS = frozenset({"low", "medium", "high", "critical", "info", "unknown"})
_SUGGESTION_FIELDS = frozenset(_SUGGESTION_FIELD_ALIASES.values())


class ResponseParser:
    """Convert ``AIResponse.text`` (or any review markdown/JSON) into typed models."""

    def __init__(self, logger: "Logger | None" = None) -> None:
        self._logger = logger

    def parse(
        self,
        text: str,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> ParsedReview:
        """Parse raw review text. Never raises for bad content."""
        warnings: list[str] = []
        raw = text if isinstance(text, str) else str(text)
        meta_base = {
            "provider": provider,
            "model": model,
            "raw_length": len(raw),
        }

        try:
            with logging_operation():
                stripped = raw.strip()
                if not stripped:
                    warnings.append("Empty response text")
                    return self._partial(
                        summary="",
                        overall_risk="unknown",
                        suggestions=[],
                        confidence=None,
                        source_format="empty",
                        warnings=warnings,
                        **meta_base,
                    )

                json_payload = self._try_extract_json(stripped, warnings)
                if json_payload is not None:
                    return self._from_json(json_payload, warnings=warnings, **meta_base)

                return self._from_markdown(stripped, warnings=warnings, **meta_base)
        except Exception as exc:  # noqa: BLE001 — never crash callers
            if self._logger is not None:
                bind_context(
                    self._logger, provider=provider, model=model, severity="warning"
                ).warning("ResponseParser unexpected error: {}", exc)
            warnings.append(f"Unexpected parse error: {exc}")
            return self._partial(
                summary=raw.strip()[:500] if isinstance(raw, str) else "",
                overall_risk="unknown",
                suggestions=[],
                confidence=None,
                source_format="unknown",
                warnings=warnings,
                **meta_base,
            )

    def parse_response(self, response: "AIResponse") -> ParsedReview:
        """Parse ``AIResponse.text`` and attach provider/model metadata."""
        return self.parse(
            response.text,
            provider=response.provider,
            model=response.model,
        )

    # ------------------------------------------------------------------ JSON
    def _try_extract_json(
        self, text: str, warnings: list[str]
    ) -> dict[str, Any] | None:
        candidates: list[str] = []
        if text.lstrip().startswith("{") or text.lstrip().startswith("```"):
            candidates.append(text)
        for match in _FENCED_JSON_RE.finditer(text):
            candidates.append(match.group(1))

        start = text.find("{")
        if start >= 0:
            depth = 0
            for idx in range(start, len(text)):
                ch = text[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        chunk = text[start : idx + 1]
                        if chunk not in candidates:
                            candidates.append(chunk)
                        break

        for candidate in candidates:
            data, repair_warnings = try_parse_json(candidate)
            warnings.extend(repair_warnings)
            if data is None:
                if "Malformed JSON" not in " ".join(repair_warnings):
                    warnings.append("Malformed JSON ignored: parse failed")
                continue
            validated, schema_warnings = validate_review_document(data)
            warnings.extend(schema_warnings)
            if validated is not None:
                return validated
            warnings.append("JSON root was not an object; falling back to markdown")

        return None

    def _from_json(
        self,
        data: dict[str, Any],
        *,
        warnings: list[str],
        provider: str | None,
        model: str | None,
        raw_length: int,
    ) -> ParsedReview:
        summary = _as_str(data.get("summary") or data.get("overview") or "")
        risk = _normalize_risk(
            data.get("overall_risk")
            or data.get("risk_level")
            or data.get("risk")
            or "unknown",
            warnings,
        )
        confidence = _parse_confidence(data.get("confidence"), warnings)

        raw_findings = data.get("suggestions")
        if raw_findings is None:
            raw_findings = data.get("findings")
        if raw_findings is None:
            raw_findings = []
        if not isinstance(raw_findings, list):
            warnings.append("findings/suggestions was not a list")
            raw_findings = []

        suggestions: list[ReviewSuggestion] = []
        for item in raw_findings:
            if isinstance(item, dict):
                suggestions.append(self._suggestion_from_mapping(item, warnings))
            elif isinstance(item, str) and item.strip():
                suggestions.append(ReviewSuggestion(title=item.strip()))
            else:
                warnings.append("Skipped non-object finding entry")

        suggestions = self._merge_duplicate_findings(suggestions, warnings)
        return self._finalize(
            summary=summary,
            overall_risk=risk,
            suggestions=suggestions,
            confidence=confidence,
            source_format="json",
            warnings=warnings,
            provider=provider,
            model=model,
            raw_length=raw_length,
        )

    # -------------------------------------------------------------- Markdown
    def _from_markdown(
        self,
        text: str,
        *,
        warnings: list[str],
        provider: str | None,
        model: str | None,
        raw_length: int,
    ) -> ParsedReview:
        sections = self._split_sections(text)
        top_kv = self._collect_key_values(text)

        summary = ""
        risk = "unknown"
        confidence: float | None = None
        suggestions: list[ReviewSuggestion] = []

        for name, body in sections:
            key = _norm_key(name)
            if key in _SUMMARY_ALIASES:
                summary = body.strip() or summary
            elif key in _RISK_ALIASES:
                risk = _normalize_risk(body.strip() or "unknown", warnings)
            elif key in _CONFIDENCE_ALIASES:
                confidence = _parse_confidence(body.strip(), warnings)
            elif key in _FINDINGS_ALIASES:
                suggestions.extend(self._parse_findings_body(body, warnings))
            elif key.startswith("finding") or name.lower().startswith("finding:"):
                title = _strip_finding_prefix(name)
                block = f"## {title}\n{body}" if title else body
                suggestions.extend(self._parse_findings_body(block, warnings))

        if not summary and "summary" in top_kv:
            summary = top_kv["summary"]
        if risk == "unknown":
            for alias in ("overall_risk", "risk_level", "risk"):
                if alias in top_kv:
                    risk = _normalize_risk(top_kv[alias], warnings)
                    break
        if confidence is None:
            for alias in ("confidence", "score"):
                if alias in top_kv:
                    confidence = _parse_confidence(top_kv[alias], warnings)
                    break

        if confidence is None:
            match = _CONFIDENCE_INLINE_RE.search(text)
            if match:
                confidence = _parse_confidence(match.group(1), warnings)

        if not suggestions and "findings" in top_kv:
            findings_raw = top_kv["findings"].strip()
            if findings_raw and findings_raw != "[]":
                try:
                    parsed = json.loads(findings_raw)
                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict):
                                suggestions.append(
                                    self._suggestion_from_mapping(item, warnings)
                                )
                except json.JSONDecodeError:
                    warnings.append("Could not parse findings value as JSON list")

        if not suggestions and not any(
            _norm_key(name) in _FINDINGS_ALIASES for name, _ in sections
        ):
            # Bullet lists that look like findings (have nested file/severity keys)
            bullet_findings = self._parse_bullet_findings(text, warnings)
            if any(s.file or s.severity != "info" or s.recommendation for s in bullet_findings):
                suggestions.extend(bullet_findings)

        if not summary:
            guessed = self._guess_summary(text, top_kv)
            if guessed:
                summary = guessed
                warnings.append("Summary inferred from leading prose")
            else:
                warnings.append("Missing summary")

        if risk == "unknown":
            warnings.append("Missing or unknown overall risk")

        suggestions = self._merge_duplicate_findings(suggestions, warnings)
        for sug in suggestions:
            if sug.file is None and sug.title:
                warnings.append(f"Finding '{sug.title}' missing file")

        source_format = "markdown" if sections else "key_value"
        return self._finalize(
            summary=summary,
            overall_risk=risk,
            suggestions=suggestions,
            confidence=confidence,
            source_format=source_format,
            warnings=warnings,
            provider=provider,
            model=model,
            raw_length=raw_length,
        )

    def _split_sections(self, text: str) -> list[tuple[str, str]]:
        """Split on the shallowest heading level; deeper headings stay in bodies."""
        lines = text.splitlines()
        levels = [
            len(match.group(1))
            for line in lines
            if (match := _HEADING_RE.match(line)) is not None
        ]
        if not levels:
            return []
        top_level = min(levels)

        sections: list[tuple[str, str]] = []
        current_name: str | None = None
        current_body: list[str] = []

        for line in lines:
            match = _HEADING_RE.match(line)
            if match and len(match.group(1)) == top_level:
                if current_name is not None:
                    sections.append((current_name, "\n".join(current_body).strip()))
                current_name = match.group(2).strip()
                current_body = []
            elif current_name is not None:
                current_body.append(line)

        if current_name is not None:
            sections.append((current_name, "\n".join(current_body).strip()))
        return sections

    def _parse_findings_body(self, body: str, warnings: list[str]) -> list[ReviewSuggestion]:
        if not body.strip():
            return []

        if _HEADING_RE.search(body):
            results: list[ReviewSuggestion] = []
            for name, sub_body in self._split_sections(body):
                if _norm_key(name) in _FINDINGS_ALIASES:
                    results.extend(self._parse_findings_body(sub_body, warnings))
                    continue
                title = _strip_finding_prefix(name)
                kv = self._collect_key_values(sub_body)
                mapping: dict[str, Any] = {"title": title or kv.get("title", ""), **kv}
                if not mapping.get("explanation") and not mapping.get("detail"):
                    bullets = [
                        b
                        for b in self._bullet_texts(sub_body)
                        if not _KV_RE.match(b)
                    ]
                    if bullets:
                        mapping["explanation"] = "\n".join(bullets)
                suggestion = self._suggestion_from_mapping(mapping, warnings)
                if suggestion.title or suggestion.explanation:
                    results.append(suggestion)
            return results

        return self._parse_bullet_findings(body, warnings)

    def _parse_bullet_findings(
        self, text: str, warnings: list[str]
    ) -> list[ReviewSuggestion]:
        """Group top-level bullets into findings (title bullet + nested kv bullets)."""
        results: list[ReviewSuggestion] = []
        current: dict[str, Any] | None = None
        current_indent = 0

        for line in text.splitlines():
            match = _BULLET_RE.match(line)
            if not match:
                if current is not None and line.strip() and not line.strip().startswith("#"):
                    prev = current.get("explanation") or ""
                    current["explanation"] = (prev + "\n" + line.strip()).strip()
                continue

            indent = len(match.group(1).replace("\t", "    "))
            content = match.group(3).strip()
            kv_match = _KV_RE.match(content)

            if current is None or indent <= current_indent:
                if current is not None:
                    results.append(self._suggestion_from_mapping(current, warnings))
                if kv_match and _norm_key(kv_match.group("key")) in _SUGGESTION_FIELD_ALIASES:
                    field = _SUGGESTION_FIELD_ALIASES[_norm_key(kv_match.group("key"))]
                    current = {field: kv_match.group("value").strip()}
                    current_indent = indent
                else:
                    current = {"title": content}
                    current_indent = indent
            else:
                assert current is not None
                if kv_match:
                    field = _SUGGESTION_FIELD_ALIASES.get(_norm_key(kv_match.group("key")))
                    if field:
                        current[field] = kv_match.group("value").strip()
                    else:
                        prev = current.get("explanation") or ""
                        current["explanation"] = (prev + "\n" + content).strip()
                else:
                    prev = current.get("explanation") or ""
                    current["explanation"] = (prev + "\n" + content).strip()

        if current is not None:
            results.append(self._suggestion_from_mapping(current, warnings))
        return results

    def _suggestion_from_mapping(
        self, data: dict[str, Any], warnings: list[str]
    ) -> ReviewSuggestion:
        normalized: dict[str, Any] = {}
        severity_present = False
        for key, value in data.items():
            # Schema dumps include every optional alias as null — skip empties
            # so they do not overwrite a populated canonical field.
            if value is None or value == "":
                continue
            field = _SUGGESTION_FIELD_ALIASES.get(_norm_key(str(key)))
            if field is None and _norm_key(str(key)) in _SUGGESTION_FIELDS:
                field = _norm_key(str(key))
            if field is None:
                continue
            if field == "severity":
                severity_present = True
                normalized[field] = _normalize_severity(value, warnings)
            elif field == "confidence":
                parsed_conf = _parse_confidence(value, warnings)
                if parsed_conf is not None:
                    normalized[field] = parsed_conf
            elif field in normalized and normalized[field] not in (None, ""):
                continue
            else:
                normalized[field] = value

        title = _as_str(normalized.get("title") or "")
        if not severity_present:
            warnings.append(
                f"Missing severity for finding '{title or '(untitled)'}'; defaulting to info"
            )
            normalized["severity"] = "info"

        explanation = _as_str(normalized.get("explanation") or "")
        if not title and explanation:
            title = explanation.splitlines()[0][:120]
            warnings.append("Finding title inferred from explanation")

        return ReviewSuggestion(
            title=title,
            explanation=explanation,
            recommendation=_as_str(normalized.get("recommendation") or ""),
            severity=_as_str(normalized.get("severity") or "info"),
            file=_optional_str(normalized.get("file")),
            line=normalized.get("line"),
            code_snippet=_optional_str(normalized.get("code_snippet")),
            confidence=normalized.get("confidence"),
            category=_optional_str(normalized.get("category")),
            estimated_impact=_optional_str(normalized.get("estimated_impact")),
        )

    def _collect_key_values(self, text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in text.splitlines():
            content = line.strip()
            bullet = _BULLET_RE.match(content)
            if bullet:
                content = bullet.group(3).strip()
            match = _KV_RE.match(content)
            if match:
                key = _norm_key(match.group("key"))
                result[key] = match.group("value").strip()
        return result

    def _bullet_texts(self, text: str) -> list[str]:
        items: list[str] = []
        for line in text.splitlines():
            match = _BULLET_RE.match(line)
            if match:
                items.append(match.group(3).strip())
        return items

    def _guess_summary(self, text: str, top_kv: dict[str, str]) -> str:
        if "summary" in top_kv:
            return top_kv["summary"]
        prose: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                if prose:
                    break
                continue
            if _BULLET_RE.match(stripped) or _KV_RE.match(stripped):
                if prose:
                    break
                continue
            if stripped.upper().startswith("MOCK_REVIEW"):
                continue
            if stripped.lower().startswith("digest=") or stripped.lower().startswith("pr="):
                continue
            if stripped.lower().startswith("repo="):
                continue
            prose.append(stripped)
            if len(prose) >= 3:
                break
        return " ".join(prose).strip()

    def _merge_duplicate_findings(
        self, suggestions: list[ReviewSuggestion], warnings: list[str]
    ) -> list[ReviewSuggestion]:
        """Merge findings that share title+file+line (keep richest fields)."""
        merged: dict[tuple[str, str | None, int | None], ReviewSuggestion] = {}
        order: list[tuple[str, str | None, int | None]] = []
        for sug in suggestions:
            key = (sug.title.strip().lower(), sug.file, sug.line)
            if not sug.title.strip():
                # Untitled — keep as unique by object identity key
                key = (f"__anon_{len(order)}", sug.file, sug.line)
            existing = merged.get(key)
            if existing is None:
                merged[key] = sug
                order.append(key)
                continue
            warnings.append(f"Duplicate finding merged: '{sug.title or '(untitled)'}'")
            merged[key] = ReviewSuggestion(
                title=existing.title or sug.title,
                explanation=_prefer_longer(existing.explanation, sug.explanation),
                recommendation=_prefer_longer(
                    existing.recommendation, sug.recommendation
                ),
                severity=_max_severity(existing.severity, sug.severity),
                file=existing.file or sug.file,
                line=existing.line if existing.line is not None else sug.line,
                code_snippet=existing.code_snippet or sug.code_snippet,
                confidence=_max_optional(existing.confidence, sug.confidence),
                category=existing.category or sug.category,
                estimated_impact=existing.estimated_impact or sug.estimated_impact,
            )
        return [merged[key] for key in order]

    def _estimate_confidence(
        self,
        *,
        summary: str,
        overall_risk: str,
        suggestions: list[ReviewSuggestion],
        confidence: float | None,
        warnings: list[str],
    ) -> float:
        if confidence is not None:
            return confidence
        score = 0.35
        if summary.strip():
            score += 0.2
        if overall_risk not in {"", "unknown"}:
            score += 0.15
        if suggestions:
            score += 0.15
            with_file = sum(1 for s in suggestions if s.file)
            with_sev = sum(1 for s in suggestions if s.severity and s.severity != "info")
            score += 0.1 * (with_file / len(suggestions))
            score += 0.05 * (with_sev / len(suggestions))
        # Penalize for parse warnings
        score -= min(0.25, 0.03 * len(warnings))
        estimated = max(0.05, min(0.95, round(score, 3)))
        warnings.append(f"Confidence estimated at {estimated:.3f} (missing explicit value)")
        return estimated

    def _finalize(
        self,
        *,
        summary: str,
        overall_risk: str,
        suggestions: list[ReviewSuggestion],
        confidence: float | None,
        source_format: str,
        warnings: list[str],
        provider: str | None,
        model: str | None,
        raw_length: int,
    ) -> ParsedReview:
        confidence = self._estimate_confidence(
            summary=summary,
            overall_risk=overall_risk,
            suggestions=suggestions,
            confidence=confidence,
            warnings=warnings,
        )
        # Normalize severities one more pass for consistency
        normalized_suggestions: list[ReviewSuggestion] = []
        for sug in suggestions:
            sev = _normalize_severity(sug.severity, warnings)
            if sev != sug.severity:
                sug = sug.model_copy(update={"severity": sev})
            normalized_suggestions.append(sug)
        suggestions = normalized_suggestions

        useful = bool(summary.strip()) or bool(suggestions)
        hard_fail = (
            not useful
            or source_format == "empty"
            or any(w.startswith("Unexpected parse error") for w in warnings)
        )
        is_partial = hard_fail or (
            (not summary.strip() or overall_risk == "unknown") and bool(warnings)
        )

        if not useful and "Could not extract structured review fields" not in warnings:
            warnings.append("Could not extract structured review fields")

        unique_warnings = list(dict.fromkeys(warnings))
        error_codes = _warning_codes(unique_warnings)
        metadata = ReviewMetadata(
            source_format=source_format,
            provider=provider,
            model=model,
            raw_length=raw_length,
            suggestion_count=len(suggestions),
            parse_warnings=unique_warnings,
            extra={
                "error_codes": error_codes,
                "partial_recovery": is_partial,
                "confidence_estimated": any(
                    w.startswith("Confidence estimated") for w in unique_warnings
                ),
            },
        )

        if self._logger is not None:
            bind_context(
                self._logger,
                provider=provider,
                model=model,
                severity=overall_risk if overall_risk not in {"", "unknown"} else "info",
            ).debug(
                "ResponseParser done — format={}, suggestions={}, partial={}, warnings={}",
                source_format,
                len(suggestions),
                is_partial,
                len(metadata.parse_warnings),
            )

        kwargs = {
            "summary": summary,
            "overall_risk": overall_risk,
            "suggestions": suggestions,
            "confidence": confidence,
            "metadata": metadata,
        }
        if is_partial:
            return PartialReviewResult(**kwargs)
        return ReviewResult(**kwargs)

    def _partial(
        self,
        *,
        summary: str,
        overall_risk: str,
        suggestions: list[ReviewSuggestion],
        confidence: float | None,
        source_format: str,
        warnings: list[str],
        provider: str | None,
        model: str | None,
        raw_length: int,
    ) -> PartialReviewResult:
        if confidence is None and (summary.strip() or suggestions):
            confidence = self._estimate_confidence(
                summary=summary,
                overall_risk=overall_risk,
                suggestions=suggestions,
                confidence=None,
                warnings=warnings,
            )
        unique = list(dict.fromkeys(warnings))
        return PartialReviewResult(
            summary=summary,
            overall_risk=overall_risk,
            suggestions=suggestions,
            confidence=confidence,
            metadata=ReviewMetadata(
                source_format=source_format,
                provider=provider,
                model=model,
                raw_length=raw_length,
                suggestion_count=len(suggestions),
                parse_warnings=unique,
                extra={
                    "error_codes": _warning_codes(unique),
                    "partial_recovery": True,
                    "confidence_estimated": any(
                        w.startswith("Confidence estimated") for w in unique
                    ),
                },
            ),
        )


def _norm_key(value: str) -> str:
    text = value.strip().lower().replace("-", "_").replace(" ", "_")
    return re.sub(r"_+", "_", text).strip("_")


def _as_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _optional_str(value: object) -> str | None:
    text = _as_str(value)
    return text or None


def _normalize_risk(value: object, warnings: list[str]) -> str:
    text = _as_str(value).lower()
    for token in re.split(r"[^\w]+", text):
        if token in _VALID_RISKS:
            return token
    if text and text != "unknown":
        warnings.append(f"Unrecognized risk value '{value}'; using unknown")
    return "unknown"


def _normalize_severity(value: object, warnings: list[str]) -> str:
    text = _as_str(value).lower()
    for token in re.split(r"[^\w]+", text):
        if token in {"warning"}:
            return "medium"
        if token in {"error"}:
            return "high"
        if token in _VALID_RISKS or token == "info":
            return token
    if text:
        warnings.append(f"Unrecognized severity '{value}'; defaulting to info")
    return "info"


def _parse_confidence(value: object, warnings: list[str]) -> float | None:
    if value is None or value == "":
        return None
    raw = value
    if isinstance(value, (int, float)):
        number = float(value)
        had_percent = False
    else:
        text = _as_str(value)
        had_percent = "%" in text
        try:
            number = float(text.rstrip("%").strip())
        except ValueError:
            warnings.append(f"Could not parse confidence '{value}'")
            return None
    if had_percent or number > 1.0:
        number = number / 100.0
    if number < 0.0 or number > 1.0:
        warnings.append(f"Confidence out of range '{raw}'; clamped")
        number = max(0.0, min(1.0, number))
    return number


def _strip_finding_prefix(name: str) -> str:
    cleaned = re.sub(r"^(finding|suggestion|issue)\s*[:\-–]?\s*", "", name, flags=re.I)
    return cleaned.strip()


_SEVERITY_RANK = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
    "unknown": 0,
}


def _prefer_longer(a: str, b: str) -> str:
    a = a or ""
    b = b or ""
    return a if len(a) >= len(b) else b


def _max_severity(a: str, b: str) -> str:
    return a if _SEVERITY_RANK.get(a, 0) >= _SEVERITY_RANK.get(b, 0) else b


def _max_optional(a: float | None, b: float | None) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def _warning_codes(warnings: list[str]) -> list[str]:
    """Map human warnings to stable machine-readable codes for clients."""
    codes: list[str] = []
    rules: list[tuple[str, str]] = [
        ("Empty response", "EMPTY_RESPONSE"),
        ("Malformed JSON", "MALFORMED_JSON"),
        ("JSON repair", "JSON_REPAIRED"),
        ("JSON schema validation failed", "SCHEMA_VALIDATION_FAILED"),
        ("JSON schema validated", "SCHEMA_OK"),
        ("Duplicate finding merged", "DUPLICATE_MERGED"),
        ("Confidence estimated", "CONFIDENCE_ESTIMATED"),
        ("Missing summary", "MISSING_SUMMARY"),
        ("Missing or unknown overall risk", "MISSING_RISK"),
        ("Missing severity", "MISSING_SEVERITY"),
        ("Unrecognized severity", "SEVERITY_NORMALIZED"),
        ("Unrecognized risk", "RISK_NORMALIZED"),
        ("missing file", "MISSING_FILE"),
        ("Could not extract structured", "NO_STRUCTURE"),
        ("Unexpected parse error", "UNEXPECTED_ERROR"),
        ("Partial", "PARTIAL_RECOVERY"),
    ]
    joined_lower = [w.lower() for w in warnings]
    for needle, code in rules:
        if any(needle.lower() in w for w in joined_lower):
            codes.append(code)
    return list(dict.fromkeys(codes))
