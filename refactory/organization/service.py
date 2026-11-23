"""Organization rules — CRUD, audit, import/export, RuleEngine adapter."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from refactory.organization.defaults import DEFAULT_ORGANIZATION_RULES
from refactory.organization.models import OrganizationRuleOut, OrganizationRulePayload
from refactory.rules.engine import RuleContext, RuleEngine
from refactory.rules.models import (
    Rule,
    RuleCategory,
    RuleCondition,
    RuleSeverity,
    RuleViolation,
)

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.db.persistence import PersistenceService
    from refactory.db.query_service import RepositoryQueryService
    from refactory.db.session import SessionFactory


_RULE_TYPE_TO_CATEGORY: dict[str, str] = {
    "branch_naming": "branch_naming",
    "commit_message": "commit_message",
    "pull_request": "pr_title",
    "file_path": "forbidden_path",
    "file_pattern": "forbidden_path",
    "code_pattern": "security_policy",
    "documentation": "stale_docs",
    "testing": "required_tests",
    "security": "security_policy",
    "architecture": "architecture_layer",
    "custom": "custom",
}

_SEVERITY_MAP: dict[str, RuleSeverity] = {
    "blocker": RuleSeverity.BLOCKER,
    "critical": RuleSeverity.ERROR,
    "error": RuleSeverity.ERROR,
    "warning": RuleSeverity.WARNING,
    "info": RuleSeverity.INFO,
}


class OrganizationRuleService:
    """Persist and evaluate organization policies (additive to built-ins)."""

    def __init__(
        self,
        *,
        logger: "Logger",
        session_factory: "SessionFactory",
        persistence_service: "PersistenceService | None" = None,
        query_service: "RepositoryQueryService | None" = None,
        rule_engine: RuleEngine | None = None,
    ) -> None:
        self._logger = logger
        self._sessions = session_factory
        self._persistence = persistence_service
        self._query = query_service
        self._engine = rule_engine or RuleEngine(logger=logger)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_rules(
        self,
        *,
        enabled: bool | None = None,
        search: str | None = None,
        organization_id: str | None = None,
        team_id: str | None = None,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        """List rules with optional org/team scope filters.

        ``scope``:
          - ``None`` / ``all`` — no org/team filter (legacy)
          - ``organization`` — org-global rules (team_id is null), optionally
            filtered by ``organization_id``
          - ``team`` — team rules for ``team_id``
          - ``effective`` — org-global + team rules for precedence merge
        """
        self.ensure_defaults()
        from refactory.db.uow import UnitOfWork

        with UnitOfWork(self._sessions) as uow:
            rows = list(uow.organization_rules.list_all())
            if enabled is not None:
                rows = [r for r in rows if bool(r.enabled) is enabled]
            out = [self._to_dict(r) for r in rows]

        scope_key = (scope or "all").lower()
        if scope_key == "organization":
            out = [r for r in out if not r.get("team_id")]
            if organization_id:
                out = [
                    r
                    for r in out
                    if not r.get("organization_id")
                    or r.get("organization_id") == organization_id
                ]
        elif scope_key == "team":
            if team_id:
                out = [r for r in out if r.get("team_id") == team_id]
            else:
                out = [r for r in out if r.get("team_id")]
        elif scope_key == "effective":
            org_rules = [
                r
                for r in out
                if not r.get("team_id")
                and (
                    not organization_id
                    or not r.get("organization_id")
                    or r.get("organization_id") == organization_id
                )
            ]
            team_rules = (
                [r for r in out if r.get("team_id") == team_id] if team_id else []
            )
            # Precedence: org first, then team (team overrides same name later)
            by_name: dict[str, dict[str, Any]] = {}
            for r in org_rules:
                by_name[str(r.get("name") or r.get("id"))] = r
            for r in team_rules:
                by_name[str(r.get("name") or r.get("id"))] = r
            out = list(by_name.values())

        if search:
            q = search.lower()
            out = [
                r
                for r in out
                if q in (r.get("name") or "").lower()
                or q in (r.get("description") or "").lower()
                or q in (r.get("message") or "").lower()
                or q in (r.get("rule_type") or "").lower()
            ]
        return out

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        from refactory.db.uow import UnitOfWork

        with UnitOfWork(self._sessions) as uow:
            row = uow.organization_rules.get_by_id(rule_id)
            return self._to_dict(row) if row else None

    def create_rule(
        self, payload: OrganizationRulePayload | dict[str, Any], *, actor: str = "local"
    ) -> dict[str, Any]:
        data = self._normalize_payload(payload)
        from refactory.db.uow import UnitOfWork

        with UnitOfWork(self._sessions) as uow:
            row = uow.organization_rules.create(**data)
            created = self._to_dict(row)
            uow.organization_rule_audits.create(
                rule_id=row.id,
                action="created",
                actor=actor,
                changes={"after": created},
            )
        self._log_activity("organization-rule-created", created)
        return created

    def update_rule(
        self,
        rule_id: str,
        payload: OrganizationRulePayload | dict[str, Any],
        *,
        actor: str = "local",
    ) -> dict[str, Any] | None:
        data = self._normalize_payload(payload, for_update=True)
        from refactory.db.uow import UnitOfWork

        with UnitOfWork(self._sessions) as uow:
            before_row = uow.organization_rules.get_by_id(rule_id)
            if before_row is None:
                return None
            before = self._to_dict(before_row)
            data["updated_at"] = datetime.now(timezone.utc)
            row = uow.organization_rules.update(rule_id, **data)
            after = self._to_dict(row) if row else None
            if after is None:
                return None
            uow.organization_rule_audits.create(
                rule_id=rule_id,
                action="updated",
                actor=actor,
                changes={"before": before, "after": after},
            )
        self._log_activity("organization-rule-updated", after)
        return after

    def delete_rule(self, rule_id: str, *, actor: str = "local") -> bool:
        from refactory.db.uow import UnitOfWork

        with UnitOfWork(self._sessions) as uow:
            before_row = uow.organization_rules.get_by_id(rule_id)
            if before_row is None:
                return False
            before = self._to_dict(before_row)
            ok = uow.organization_rules.delete(rule_id)
            if ok:
                uow.organization_rule_audits.create(
                    rule_id=rule_id,
                    action="deleted",
                    actor=actor,
                    changes={"before": before},
                )
        if ok:
            self._log_activity("organization-rule-deleted", before)
        return ok

    def set_enabled(
        self, rule_id: str, enabled: bool, *, actor: str = "local"
    ) -> dict[str, Any] | None:
        from refactory.db.uow import UnitOfWork

        action = "enabled" if enabled else "disabled"
        with UnitOfWork(self._sessions) as uow:
            row = uow.organization_rules.get_by_id(rule_id)
            if row is None:
                return None
            before = self._to_dict(row)
            row = uow.organization_rules.update(
                rule_id, enabled=enabled, updated_at=datetime.now(timezone.utc)
            )
            after = self._to_dict(row) if row else None
            if after:
                uow.organization_rule_audits.create(
                    rule_id=rule_id,
                    action=action,
                    actor=actor,
                    changes={"before": before, "after": after},
                )
        if after:
            self._log_activity(f"organization-rule-{action}", after)
        return after

    def duplicate_rule(
        self, rule_id: str, *, actor: str = "local"
    ) -> dict[str, Any] | None:
        src = self.get_rule(rule_id)
        if src is None:
            return None
        payload = {**src}
        payload.pop("id", None)
        payload.pop("created_at", None)
        payload.pop("updated_at", None)
        payload["name"] = f"{src['name']} (copy)"
        payload["enabled"] = False
        return self.create_rule(payload, actor=actor)

    def list_audit(self, rule_id: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
        from refactory.db.uow import UnitOfWork

        with UnitOfWork(self._sessions) as uow:
            if rule_id:
                rows = uow.organization_rule_audits.list_by_rule(rule_id, limit=limit)
            else:
                rows = uow.organization_rule_audits.list_recent(limit=limit)
            return [
                {
                    "id": r.id,
                    "rule_id": r.rule_id,
                    "action": r.action,
                    "actor": r.actor or "local",
                    "changes": r.changes or {},
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]

    # ------------------------------------------------------------------
    # Import / export
    # ------------------------------------------------------------------

    def export_rules(self) -> dict[str, Any]:
        rules = self.list_rules()
        # Strip persistence ids for portable export? Keep name-centric; include ids.
        portable = []
        for r in rules:
            item = dict(r)
            item.pop("created_at", None)
            item.pop("updated_at", None)
            portable.append(item)
        return {
            "version": "1.0",
            "type": "refactory.organization_rules",
            "rules": portable,
        }

    def import_rules(
        self,
        payload: dict[str, Any] | list[Any],
        *,
        replace: bool = False,
        actor: str = "local",
    ) -> dict[str, Any]:
        if isinstance(payload, list):
            rules = payload
        else:
            rules = payload.get("rules") or []
        if not isinstance(rules, list):
            raise ValueError("Import payload must include a 'rules' array")

        created = 0
        updated = 0
        if replace:
            existing = self.list_rules()
            for row in existing:
                self.delete_rule(row["id"], actor=actor)

        by_name = {r["name"]: r for r in self.list_rules()}
        for item in rules:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            name = str(item["name"])
            if name in by_name and not replace:
                self.update_rule(by_name[name]["id"], item, actor=actor)
                updated += 1
            else:
                clean = dict(item)
                clean.pop("id", None)
                self.create_rule(clean, actor=actor)
                created += 1
        return {"created": created, "updated": updated, "total": created + updated}

    # ------------------------------------------------------------------
    # Engine adapter + preview
    # ------------------------------------------------------------------

    def enabled_as_rules(
        self,
        *,
        organization_id: str | None = None,
        team_id: str | None = None,
    ) -> list[Rule]:
        """Convert enabled rules to RuleEngine objects.

        Precedence for merge: organization (team_id null) then team.
        Callers should add repository ``rules.yaml`` after this list.
        """
        if organization_id or team_id:
            rows = self.list_rules(
                enabled=True,
                organization_id=organization_id,
                team_id=team_id,
                scope="effective",
            )
        else:
            rows = self.list_rules(enabled=True)
        return [self.to_engine_rule(r) for r in rows]

    def to_engine_rule(self, row: dict[str, Any]) -> Rule:
        rule_type = str(row.get("rule_type") or "custom")
        category_name = str(
            row.get("category") or _RULE_TYPE_TO_CATEGORY.get(rule_type, "custom")
        )
        try:
            category = RuleCategory(category_name)
        except ValueError:
            category = RuleCategory.CUSTOM

        severity_key = str(row.get("severity") or "warning").lower()
        severity = _SEVERITY_MAP.get(severity_key, RuleSeverity.WARNING)
        blocking = bool(row.get("blocking")) or severity_key in {"blocker", "critical"}

        conditions: list[RuleCondition] = []
        for c in row.get("conditions") or []:
            if not isinstance(c, dict):
                continue
            conditions.append(
                RuleCondition(
                    field=str(c.get("field") or ""),
                    operator=str(c.get("operator") or "matches"),
                    value=c.get("value"),
                    pattern=str(c.get("pattern") or ""),
                )
            )

        source = "team" if row.get("team_id") else "organization"
        return Rule(
            name=str(row.get("name") or "unnamed"),
            description=str(row.get("description") or ""),
            severity=severity,
            enabled=bool(row.get("enabled", True)),
            category=category,
            conditions=conditions,
            message=str(row.get("message") or ""),
            blocking=blocking,
            source=source,
            rule_type=rule_type,
            documentation_url=str(row.get("documentation_url") or ""),
            condition_logic=str(row.get("condition_logic") or "and"),
            id=str(row.get("id") or ""),
        )

    def preview(
        self,
        repo_root: Path,
        *,
        rule: dict[str, Any] | None = None,
        rule_id: str | None = None,
        branch_name: str = "",
        commit_message: str = "",
        changed_files: list[str] | None = None,
    ) -> dict[str, Any]:
        """Evaluate a draft or saved org rule against the latest repository context."""
        if rule is None and rule_id:
            stored = self.get_rule(rule_id)
            if stored is None:
                raise ValueError(f"Organization rule '{rule_id}' not found")
            rule = stored
        if not rule:
            raise ValueError("Provide rule body or rule_id for preview")

        engine_rule = self.to_engine_rule(rule)
        root = repo_root.resolve()
        ctx = self._build_preview_context(
            root,
            branch_name=branch_name,
            commit_message=commit_message,
            changed_files=changed_files or [],
        )
        self._engine.clear_rules()
        self._engine.add_rule(engine_rule)
        result = self._engine.evaluate(ctx)
        return {
            "passed": result.passed,
            "rules_evaluated": result.rules_evaluated,
            "violations": [self._violation_dict(v) for v in result.violations],
            "context": {
                "branch_name": ctx.branch_name,
                "commit_message": ctx.commit_message,
                "changed_files": ctx.changed_files[:50],
            },
        }

    def ensure_defaults(self) -> int:
        """Seed example organization policies when the table is empty."""
        from refactory.db.uow import UnitOfWork

        with UnitOfWork(self._sessions) as uow:
            if uow.organization_rules.count() > 0:
                return 0
            for item in DEFAULT_ORGANIZATION_RULES:
                data = self._normalize_payload(item)
                row = uow.organization_rules.create(**data)
                uow.organization_rule_audits.create(
                    rule_id=row.id,
                    action="seeded",
                    actor="system",
                    changes={"after": self._to_dict(row)},
                )
            return len(DEFAULT_ORGANIZATION_RULES)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_preview_context(
        self,
        root: Path,
        *,
        branch_name: str,
        commit_message: str,
        changed_files: list[str],
    ) -> RuleContext:
        files = list(changed_files)
        if not files:
            # Use a sample of tracked python files for content/security previews
            for py in sorted(root.rglob("*.py"))[:40]:
                if any(p in py.parts for p in (".git", "node_modules", ".venv", "venv")):
                    continue
                try:
                    files.append(str(py.relative_to(root)).replace("\\", "/"))
                except ValueError:
                    continue

        file_contents: dict[str, str] = {}
        imports: list[str] = []
        for rel in files[:40]:
            path = root / rel
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(text) > 100_000:
                text = text[:100_000]
            file_contents[rel] = text
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("import ") or s.startswith("from "):
                    imports.append(s)

        if not branch_name:
            branch_name = "feature/preview"
        if not commit_message:
            commit_message = "feat: preview organization rule"

        return RuleContext(
            {
                "branch_name": branch_name,
                "commit_message": commit_message,
                "changed_files": files,
                "imports": imports,
                "file_contents": file_contents,
                "file_sizes": {k: len(v.splitlines()) for k, v in file_contents.items()},
                "function_sizes": {},
                "content": "\n".join(file_contents.values())[:200_000],
            }
        )

    def _log_activity(self, command: str, payload: dict[str, Any]) -> None:
        if self._persistence is None or self._query is None:
            return
        try:
            # Attach to first known repository when available
            # Activity requires repository_id — skip if none configured.
            # Callers that have repo context may also persist; this is best-effort.
            self._logger.info("organization rule activity: {} name={}", command, payload.get("name"))
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("organization rule activity skipped: {}", exc)

    def log_activity_for_repo(
        self, repository_id: str, command: str, payload: dict[str, Any]
    ) -> None:
        if self._persistence is None:
            return
        try:
            self._persistence.persist_analysis_run(
                repository_id=repository_id,
                command=command,
                result_type="organization_rule",
                status="completed",
                result_data={
                    "rule_id": payload.get("id"),
                    "name": payload.get("name"),
                    "enabled": payload.get("enabled"),
                    "severity": payload.get("severity"),
                    "rule_type": payload.get("rule_type"),
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Failed to persist org-rule activity: {}", exc)

    @staticmethod
    def _violation_dict(v: RuleViolation) -> dict[str, Any]:
        return {
            "rule": v.rule_name,
            "message": v.message,
            "severity": v.severity.value if hasattr(v.severity, "value") else str(v.severity),
            "blocking": v.blocking,
            "file_path": v.file_path,
            "detail": "",
            "source": getattr(v, "source", "organization") or "organization",
            "documentation_url": getattr(v, "documentation_url", "") or "",
        }

    @staticmethod
    def _to_dict(row: Any) -> dict[str, Any]:
        """Serialize an ORM row to the public organization-rule DTO.

        Always includes ``blocking`` (never omit / never leave unset).
        """
        team_id = getattr(row, "team_id", None)
        out = OrganizationRuleOut(
            id=str(row.id),
            name=str(row.name),
            description=row.description or "",
            category=row.category or "custom",
            severity=row.severity or "warning",
            enabled=bool(row.enabled),
            rule_type=row.rule_type or "custom",
            conditions=list(row.conditions or []),
            condition_logic=row.condition_logic or "and",
            message=row.message or "",
            documentation_url=row.documentation_url or "",
            blocking=bool(getattr(row, "blocking", False)),
            organization_id=getattr(row, "organization_id", None),
            team_id=team_id,
            created_at=row.created_at.isoformat() if row.created_at else None,
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
            source="team" if team_id else "organization",
        )
        return out.model_dump(mode="json")

    def _normalize_payload(
        self, payload: OrganizationRulePayload | dict[str, Any], *, for_update: bool = False
    ) -> dict[str, Any]:
        if isinstance(payload, OrganizationRulePayload):
            raw = payload.model_dump()
        else:
            raw = dict(payload)
        name = str(raw.get("name") or "").strip()
        if not name:
            raise ValueError("Rule name is required")
        severity = str(raw.get("severity") or "warning").lower()
        if severity == "critical":
            raw["blocking"] = True
        rule_type = str(raw.get("rule_type") or "custom")
        category = str(
            raw.get("category") or _RULE_TYPE_TO_CATEGORY.get(rule_type, "custom")
        )
        conditions = raw.get("conditions") or []
        if not isinstance(conditions, list):
            conditions = []
        data = {
            "name": name,
            "description": str(raw.get("description") or ""),
            "category": category,
            "severity": severity,
            "enabled": bool(raw.get("enabled", True)),
            "rule_type": rule_type,
            "conditions": conditions,
            "condition_logic": str(raw.get("condition_logic") or "and"),
            "message": str(raw.get("message") or ""),
            "documentation_url": str(raw.get("documentation_url") or ""),
            "blocking": bool(raw.get("blocking", False))
            or severity in {"blocker", "critical"},
            "organization_id": raw.get("organization_id") or None,
            "team_id": raw.get("team_id") or None,
        }
        if for_update:
            data.pop("name", None)
            # Allow name updates
            data["name"] = name
        return data
