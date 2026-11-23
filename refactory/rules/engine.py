"""RuleEngine — evaluates configurable engineering rules against code changes.

Loads rules from .refactory/rules.yaml or .refactory/rules.json.
Evaluates rules against repository state, diffs, and code structures.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from refactory.rules.models import (
    Rule,
    RuleCategory,
    RuleCondition,
    RuleEvaluationResult,
    RuleSet,
    RuleSeverity,
    RuleViolation,
)

if TYPE_CHECKING:
    from loguru import Logger


class RuleEngine:
    """Configurable rule engine for engineering policies."""

    def __init__(self, logger: "Logger") -> None:
        self._logger = logger
        self._rules: list[Rule] = []

    def load_rules(self, repo_root: Path) -> int:
        """Load rules from .refactory/rules.yaml or .refactory/rules.json.

        Raises ValueError when a rules file exists but cannot be parsed,
        so callers know the configuration is broken.
        """
        loaded = 0
        yaml_path = repo_root / ".refactory" / "rules.yaml"
        json_path = repo_root / ".refactory" / "rules.json"

        if yaml_path.is_file():
            loaded += self._load_yaml(yaml_path)
        if json_path.is_file():
            loaded += self._load_json(json_path)

        if loaded == 0 and (yaml_path.is_file() or json_path.is_file()):
            self._logger.warning(
                "Rules file(s) found but 0 rules loaded from {} — check your rules.yaml schema",
                repo_root,
            )

        self._logger.info("Loaded {} rules from {}", loaded, repo_root)
        return loaded

    def add_rule(self, rule: Rule) -> None:
        """Add a rule programmatically."""
        self._rules.append(rule)

    def add_rules(self, rules: list[Rule]) -> None:
        """Add multiple rules."""
        self._rules.extend(rules)

    def clear_rules(self) -> None:
        """Remove all loaded rules."""
        self._rules.clear()

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)

    def evaluate(self, context: RuleContext) -> RuleEvaluationResult:
        """Evaluate all enabled rules against the given context."""
        violations: list[RuleViolation] = []
        evaluated = 0
        passed = 0

        for rule in self._rules:
            if not rule.enabled:
                continue
            evaluated += 1
            rule_violations = self._evaluate_rule(rule, context)
            if rule_violations:
                violations.extend(rule_violations)
            else:
                passed += 1

        blocking = sum(1 for v in violations if v.blocking)
        self._logger.info(
            "Rule evaluation: {}/{} passed, {} violations ({} blocking)",
            passed, evaluated, len(violations), blocking,
        )
        return RuleEvaluationResult(
            violations=violations,
            rules_evaluated=evaluated,
            rules_passed=passed,
            rules_failed=evaluated - passed,
            blocking_violations=blocking,
            passed=blocking == 0,
        )

    def _evaluate_rule(self, rule: Rule, context: "RuleContext") -> list[RuleViolation]:
        """Evaluate a single rule."""
        evaluator = _EVALUATORS.get(rule.category)
        if evaluator is None:
            # Custom / unknown categories: content conditions are prohibitions
            # (match → violation), matching security_policy semantics used by
            # organization "No TODO…" style rules with rule_type=custom.
            if _has_content_condition(rule):
                return _eval_security_policy(rule, context)
            # Organization/team custom rules: conditions describe when the rule
            # fires (match → violation). Specialized categories (branch_naming,
            # commit_message, …) keep allowlist semantics via _EVALUATORS.
            if rule.category == RuleCategory.CUSTOM or getattr(rule, "source", "") in {
                "organization",
                "team",
            }:
                return self._evaluate_custom(rule, context)
            return self._evaluate_generic(rule, context)
        return evaluator(rule, context)

    def _evaluate_custom(self, rule: Rule, context: "RuleContext") -> list[RuleViolation]:
        """Custom/org policy: conditions matched → emit violation (denylist)."""
        if not rule.conditions:
            return []
        results: list[bool] = []
        for c in rule.conditions:
            op = (c.operator or "matches").lower()
            pattern = c.pattern or str(c.value if c.value is not None else "")
            # Incomplete match/contains conditions must not vacuously fire.
            if op in {"matches", "contains"} and not pattern:
                results.append(False)
            else:
                results.append(self._check_condition(c, context))
        logic = (rule.condition_logic or "and").lower()
        matched = all(results) if logic != "or" else any(results)
        if matched:
            return [
                _violation(
                    rule, message=rule.message or f"Rule '{rule.name}' violated"
                )
            ]
        return []

    def _evaluate_generic(self, rule: Rule, context: "RuleContext") -> list[RuleViolation]:
        """Allowlist evaluation: conditions must hold or the rule fails."""
        if not rule.conditions:
            return []
        results = [self._check_condition(c, context) for c in rule.conditions]
        logic = (rule.condition_logic or "and").lower()
        ok = all(results) if logic != "or" else any(results)
        if ok:
            return []
        return [_violation(rule, message=rule.message or f"Rule '{rule.name}' violated")]

    def _check_condition(self, condition: RuleCondition, context: "RuleContext") -> bool:
        """Check a single condition against context."""
        raw = context.get(condition.field, "")
        value = _as_text(raw)
        op = (condition.operator or "matches").lower()
        needle = str(condition.value if condition.value is not None else "")
        pattern = condition.pattern or needle

        if op == "matches":
            return bool(re.search(pattern, value)) if pattern else True
        if op == "not_matches":
            return not bool(re.search(pattern, value)) if pattern else True
        if op == "contains":
            return needle in value
        if op == "not_contains":
            return needle not in value
        if op == "starts_with":
            return value.startswith(needle)
        if op == "ends_with":
            return value.endswith(needle)
        if op == "equals":
            return value == needle
        if op == "exists":
            if isinstance(raw, (list, dict)):
                return len(raw) > 0
            return bool(str(raw).strip())
        if op == "missing":
            if isinstance(raw, (list, dict)):
                return len(raw) == 0
            return not bool(str(raw).strip())
        if op == "less_than":
            try:
                return float(value) < float(condition.value or 0)
            except (TypeError, ValueError):
                return False
        if op == "greater_than":
            try:
                return float(value) > float(condition.value or 0)
            except (TypeError, ValueError):
                return False
        return True

    def _load_yaml(self, path: Path) -> int:
        """Load rules from YAML file.

        Raises ValueError when every rule fails to parse so the caller
        knows the config is broken rather than silently loading 0 rules.
        """
        try:
            import yaml
        except ImportError:
            self._logger.warning("PyYAML not installed; skipping {}", path)
            return 0

        try:
            content = path.read_text(encoding="utf-8")
            data = yaml.safe_load(content) or {}
        except Exception as e:  # noqa: BLE001
            self._logger.error("Failed to read {}: {}", path, e)
            raise ValueError(f"Cannot read {path}: {e}") from e

        return self._parse_rules_data(data)

    def _load_json(self, path: Path) -> int:
        """Load rules from JSON file.

        Raises ValueError when every rule fails to parse.
        """
        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
        except Exception as e:  # noqa: BLE001
            self._logger.error("Failed to read {}: {}", path, e)
            raise ValueError(f"Cannot read {path}: {e}") from e

        return self._parse_rules_data(data)

    def _parse_rules_data(self, data: dict[str, Any]) -> int:
        """Parse rule data into Rule objects.

        Raises ValueError with a descriptive message when a rule is malformed
        so callers can surface the problem instead of silently loading 0 rules.
        """
        rules_list = data.get("rules", [])
        if not isinstance(rules_list, list):
            raise ValueError(
                "rules.yaml: 'rules' must be a list of rule objects, "
                f"got {type(rules_list).__name__}"
            )
        count = 0
        errors: list[str] = []
        for idx, rd in enumerate(rules_list):
            rule_name = rd.get("name", f"<rule #{idx}>")
            try:
                if "name" not in rd:
                    raise KeyError("'name' is required for every rule")

                raw_cat = rd.get("category", "custom")
                try:
                    category = RuleCategory(raw_cat)
                except ValueError:
                    valid = ", ".join(c.value for c in RuleCategory)
                    raise ValueError(
                        f"Rule '{rule_name}': unknown category '{raw_cat}'. "
                        f"Valid categories: {valid}"
                    ) from None

                conditions = self._parse_conditions(rd.get("conditions", []), rule_name)

                rule = Rule(
                    name=rd["name"],
                    description=rd.get("description", ""),
                    severity=RuleSeverity(rd.get("severity", "warning")),
                    enabled=rd.get("enabled", True),
                    category=category,
                    conditions=conditions,
                    message=rd.get("message", ""),
                    blocking=rd.get("blocking", False),
                )
                self._rules.append(rule)
                count += 1
            except (KeyError, ValueError, TypeError) as e:
                errors.append(str(e))
                self._logger.warning("Rule '{}': {}", rule_name, e)

        if errors and count == 0:
            raise ValueError(
                f"rules.yaml: all {len(errors)} rules failed to parse. "
                f"First error: {errors[0]}"
            )
        return count

    @staticmethod
    def _parse_conditions(raw: Any, rule_name: str) -> list[RuleCondition]:
        """Parse conditions from either list-of-dicts or a flat dict."""
        if isinstance(raw, list):
            result = []
            for i, c in enumerate(raw):
                if not isinstance(c, dict):
                    raise ValueError(
                        f"Rule '{rule_name}': condition #{i} must be a mapping, "
                        f"got {type(c).__name__}"
                    )
                result.append(RuleCondition(**c))
            return result
        if isinstance(raw, dict):
            result = []
            for key, val in raw.items():
                if key == "pattern":
                    result.append(RuleCondition(pattern=str(val), operator="matches"))
                elif key in ("max_lines", "max_size", "max_length"):
                    result.append(RuleCondition(
                        field=key, operator="greater_than", value=val,
                    ))
                else:
                    result.append(RuleCondition(field=key, value=val))
            return result
        if raw is None:
            return []
        raise ValueError(
            f"Rule '{rule_name}': 'conditions' must be a list or mapping, "
            f"got {type(raw).__name__}"
        )


class RuleContext:
    """Context for rule evaluation — carries code analysis data."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = data or {}

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get(self, key: str, default: Any = "") -> Any:
        return self._data.get(key, default)

    @property
    def data(self) -> dict[str, Any]:
        return dict(self._data)

    @property
    def branch_name(self) -> str:
        return str(self._data.get("branch_name", ""))

    @property
    def commit_message(self) -> str:
        return str(self._data.get("commit_message", ""))

    @property
    def changed_files(self) -> list[str]:
        return list(self._data.get("changed_files", []))

    @property
    def imports(self) -> list[str]:
        return list(self._data.get("imports", []))

    @property
    def file_sizes(self) -> dict[str, int]:
        return dict(self._data.get("file_sizes", {}))

    @property
    def function_sizes(self) -> dict[str, int]:
        return dict(self._data.get("function_sizes", {}))

    @property
    def file_contents(self) -> dict[str, str]:
        """Optional map of relative path → file text for content-based rules."""
        return dict(self._data.get("file_contents", {}))


# Rule evaluator functions

def _as_text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(x) for x in value)
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value if value is not None else "")


def _violation(rule: Rule, **kwargs: Any) -> RuleViolation:
    return RuleViolation(
        rule_name=rule.name,
        category=rule.category,
        severity=rule.severity,
        blocking=rule.blocking,
        source=getattr(rule, "source", None) or "builtin",
        documentation_url=getattr(rule, "documentation_url", None) or "",
        message=kwargs.pop("message", rule.message or f"Rule '{rule.name}' violated"),
        **kwargs,
    )


def _eval_branch_naming(rule: Rule, ctx: RuleContext) -> list[RuleViolation]:
    branch = ctx.branch_name
    if not branch:
        return []
    logic = (rule.condition_logic or "and").lower()
    results: list[bool] = []
    last_pattern = ""
    for cond in rule.conditions:
        pattern = cond.pattern or str(cond.value or "")
        last_pattern = pattern or last_pattern
        if not pattern:
            results.append(True)
            continue
        results.append(bool(re.search(pattern, branch)))
    if not results:
        return []
    ok = all(results) if logic != "or" else any(results)
    if ok:
        return []
    return [
        _violation(
            rule,
            message=rule.message
            or f"Branch '{branch}' doesn't match pattern '{last_pattern}'",
            context={"branch": branch, "pattern": last_pattern},
        )
    ]


def _eval_commit_message(rule: Rule, ctx: RuleContext) -> list[RuleViolation]:
    msg = ctx.commit_message
    if not msg:
        return []
    logic = (rule.condition_logic or "and").lower()
    results: list[bool] = []
    last_pattern = ""
    for cond in rule.conditions:
        pattern = cond.pattern or str(cond.value or "")
        last_pattern = pattern or last_pattern
        if not pattern:
            results.append(True)
            continue
        results.append(bool(re.search(pattern, msg)))
    if not results:
        return []
    ok = all(results) if logic != "or" else any(results)
    if ok:
        return []
    return [
        _violation(
            rule,
            message=rule.message or f"Commit message doesn't match '{last_pattern}'",
        )
    ]


def _eval_forbidden_path(rule: Rule, ctx: RuleContext) -> list[RuleViolation]:
    violations = []
    for cond in rule.conditions:
        pattern = cond.pattern or str(cond.value or "")
        if not pattern:
            continue
        for fp in ctx.changed_files:
            if re.search(pattern, fp):
                violations.append(
                    _violation(
                        rule,
                        message=rule.message or f"Forbidden path: {fp}",
                        file_path=fp,
                    )
                )
    return violations


def _eval_forbidden_import(rule: Rule, ctx: RuleContext) -> list[RuleViolation]:
    violations = []
    for cond in rule.conditions:
        forbidden = cond.pattern or str(cond.value or "")
        if not forbidden:
            continue
        for imp in ctx.imports:
            if re.search(forbidden, imp):
                violations.append(
                    _violation(
                        rule,
                        message=rule.message or f"Forbidden import: {imp}",
                    )
                )
    return violations


def _collect_import_lines(ctx: RuleContext) -> list[tuple[str, str]]:
    """Return (file_path, import_line) pairs from context imports + file bodies."""
    out: list[tuple[str, str]] = []
    for imp in ctx.imports:
        text = str(imp).strip()
        if text:
            out.append(("", text))
    for file_path, body in (ctx.file_contents or {}).items():
        for line in str(body).splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                out.append((file_path, stripped))
    return out


def _eval_architecture_layer(rule: Rule, ctx: RuleContext) -> list[RuleViolation]:
    """Prohibition-style architecture rules (controller→repository, etc.).

    Unlike generic condition evaluation (match = pass), architecture_layer treats
    ``matches`` as "violate when the pattern is found" — same semantics as
    forbidden_import. Empty import/content context is a no-op (pass), not a fail.
    """
    import_lines = _collect_import_lines(ctx)
    if not import_lines and not (ctx.file_contents or {}):
        return []

    violations: list[RuleViolation] = []
    for cond in rule.conditions:
        field = (cond.field or "imports").lower()
        if field not in {"imports", "import", "content", "source", "code"}:
            continue
        pattern = cond.pattern or str(cond.value or "")
        if not pattern:
            continue
        try:
            regex = re.compile(pattern)
        except re.error:
            continue
        op = (cond.operator or "matches").lower()

        if field in {"content", "source", "code"}:
            for file_path, text in (ctx.file_contents or {}).items():
                matched = bool(regex.search(text))
                violated = matched if op in {"matches", "contains"} else (not matched)
                if violated:
                    violations.append(
                        _violation(
                            rule,
                            message=rule.message
                            or f"Architecture rule '{rule.name}' violated in {file_path}",
                            file_path=file_path,
                        )
                    )
            continue

        # imports field — scan import lines and path:import (layer + dependency)
        any_match = False
        for file_path, line in import_lines:
            haystacks = [line]
            if file_path:
                haystacks.append(f"{file_path}:{line}")
                haystacks.append(f"{file_path} {line}")
            if any(regex.search(h) for h in haystacks):
                any_match = True
                if op in {"matches", "contains"}:
                    violations.append(
                        _violation(
                            rule,
                            message=rule.message
                            or f"Architecture rule '{rule.name}' violated: {line}",
                            file_path=file_path or "",
                        )
                    )
        if op in {"not_matches", "not_contains"} and not any_match and import_lines:
            violations.append(
                _violation(
                    rule,
                    message=rule.message
                    or f"Architecture rule '{rule.name}' violated",
                )
            )
    return violations


def _eval_max_function_size(rule: Rule, ctx: RuleContext) -> list[RuleViolation]:
    violations = []
    max_lines = 50
    for cond in rule.conditions:
        if cond.value and isinstance(cond.value, (int, float)):
            max_lines = int(cond.value)
    for func_name, size in ctx.function_sizes.items():
        if size > max_lines:
            violations.append(
                _violation(
                    rule,
                    message=rule.message
                    or f"Function '{func_name}' has {size} lines (max {max_lines})",
                    context={"function": func_name, "size": str(size), "max": str(max_lines)},
                )
            )
    return violations


def _eval_max_file_size(rule: Rule, ctx: RuleContext) -> list[RuleViolation]:
    violations = []
    max_lines = 500
    for cond in rule.conditions:
        if cond.value and isinstance(cond.value, (int, float)):
            max_lines = int(cond.value)
    for file_path, size in ctx.file_sizes.items():
        if size > max_lines:
            violations.append(
                _violation(
                    rule,
                    message=rule.message
                    or f"File '{file_path}' has {size} lines (max {max_lines})",
                    file_path=file_path,
                )
            )
    return violations


def _has_content_condition(rule: Rule) -> bool:
    return any(
        (c.field or "").lower() in {"content", "source", "code"} for c in rule.conditions
    )


def _eval_security_policy(rule: Rule, ctx: RuleContext) -> list[RuleViolation]:
    """Evaluate content-based security rules against per-file source text.

    Conditions with ``field: content`` (or ``source``) and a ``matches`` pattern
    produce one violation per matching file, with ``file_path`` set.
    """
    contents = dict(ctx.file_contents or {})
    if not contents:
        # Aggregated blob from RuleContext["content"] (org custom rules / thin gates).
        blob = str(ctx.get("content") or "")
        if blob.strip():
            contents = {"<repository>": blob}
        else:
            return []

    violations: list[RuleViolation] = []
    for cond in rule.conditions:
        field = (cond.field or "content").lower()
        if field not in {"content", "source", "code"}:
            continue
        pattern = cond.pattern or str(cond.value or "")
        if not pattern:
            continue
        try:
            regex = re.compile(pattern)
        except re.error:
            continue
        op = (cond.operator or "matches").lower()
        for file_path, text in contents.items():
            matched = bool(regex.search(text))
            violated = matched if op in {"matches", "contains"} else (not matched)
            if not violated:
                continue
            line = 0
            if matched:
                for i, line_text in enumerate(text.splitlines(), start=1):
                    if regex.search(line_text):
                        line = i
                        break
            violations.append(
                _violation(
                    rule,
                    message=rule.message
                    or f"Rule '{rule.name}' violated in {file_path}",
                    file_path=file_path,
                    line=line,
                )
            )
    return violations


def _eval_required_tests(rule: Rule, ctx: RuleContext) -> list[RuleViolation]:
    """If production paths change, require test path changes.

    conditions[0] = production path pattern; conditions[1] = test path pattern.
    """
    files = ctx.changed_files
    if not files or len(rule.conditions) < 2:
        return []
    prod = rule.conditions[0].pattern or str(rule.conditions[0].value or "")
    tests = rule.conditions[1].pattern or str(rule.conditions[1].value or "")
    if not prod or not tests:
        return []
    touches_prod = any(re.search(prod, f) for f in files)
    if not touches_prod:
        return []
    touches_tests = any(re.search(tests, f) for f in files)
    if touches_tests:
        return []
    return [
        _violation(
            rule,
            message=rule.message
            or "Production changes require accompanying test updates.",
        )
    ]


_EVALUATORS = {
    RuleCategory.BRANCH_NAMING: _eval_branch_naming,
    RuleCategory.COMMIT_MESSAGE: _eval_commit_message,
    RuleCategory.FORBIDDEN_PATH: _eval_forbidden_path,
    RuleCategory.FORBIDDEN_IMPORT: _eval_forbidden_import,
    RuleCategory.ARCHITECTURE_LAYER: _eval_architecture_layer,
    RuleCategory.MAX_FUNCTION_SIZE: _eval_max_function_size,
    RuleCategory.MAX_FILE_SIZE: _eval_max_file_size,
    RuleCategory.SECURITY_POLICY: _eval_security_policy,
    RuleCategory.REQUIRED_TESTS: _eval_required_tests,
}
