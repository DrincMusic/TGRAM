from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .authority import AuthenticatedIdentity
from .models import (
    ApprovalPolicyRule,
    GovernanceDecision,
    ProjectGovernancePolicy,
    ProjectPolicyRevision,
    ProjectRecord,
    TicketBudget,
)


class ProjectGovernance:
    """Resolve and enforce authorization without allowing project scope to drift."""

    def __init__(self, store) -> None:
        self.store = store

    @staticmethod
    def canonical_root(root: str | Path) -> str:
        return str(Path(root).resolve()).casefold()

    def project(self, project_id: str) -> ProjectRecord:
        project = next((item for item in self.store.projects() if item.id == project_id), None)
        if project is None or not project.explicitly_selected or not project.read_only:
            raise ValueError("Governance requires an explicitly registered read-only project.")
        matches = [
            item for item in self.store.projects()
            if self.canonical_root(item.root) == self.canonical_root(project.root)
        ]
        if len(matches) != 1:
            raise ValueError("Registered project roots must map to exactly one project identity.")
        wanted = self.canonical_root(project.root)
        for other in self.store.projects():
            if other.id == project.id:
                continue
            candidate = self.canonical_root(other.root)
            try:
                common = os.path.commonpath([wanted, candidate]).casefold()
            except ValueError:
                continue
            if common in {wanted, candidate}:
                raise ValueError("Registered project roots must not overlap or contain one another.")
        return project

    def policy(self, project_id: str) -> ProjectGovernancePolicy:
        project = self.project(project_id)
        existing = next(
            (item for item in self.store.project_governance_policies() if item.project_id == project_id),
            None,
        )
        if existing is not None:
            self._validate_binding(existing, project)
            return existing
        policy = ProjectGovernancePolicy(
            project_id=project.id,
            project_root=str(Path(project.root).resolve()),
        )
        policy.revision_history.append(self._revision(policy))
        self.store.save_project_governance_policy(policy)
        return policy

    def configure(
        self,
        project_id: str,
        *,
        permitted_worker_ids: list[str],
        required_validation_categories: list[str],
        plan_approvers: list[str],
        promotion_approvers: list[str],
        max_ticket_budget: TicketBudget,
        actor: str,
        reason: str,
        actor_roles: dict[str, list[str]] | None = None,
        approval_rules: list[ApprovalPolicyRule] | None = None,
        artifact_validation_requirements: dict[str, list[str]] | None = None,
        authority_mode: str | None = None,
        authority_organization_id: str | None = None,
        authenticated_role_bindings: dict[str, list[str]] | None = None,
    ) -> ProjectGovernancePolicy:
        project = self.project(project_id)
        if not actor.strip() or not reason.strip():
            raise ValueError("Project policy changes require an attributable actor and reason.")
        for label, values in (
            ("permitted workers", permitted_worker_ids),
            ("plan approvers", plan_approvers),
            ("promotion approvers", promotion_approvers),
        ):
            if not values or any(not item.strip() for item in values):
                raise ValueError(f"Project policy requires explicit {label}.")
        current = next(
            (item for item in self.store.project_governance_policies() if item.project_id == project_id),
            None,
        )
        policy = ProjectGovernancePolicy(
            id=current.id if current else ProjectGovernancePolicy(
                project_id=project.id, project_root=str(Path(project.root).resolve())
            ).id,
            project_id=project.id,
            project_root=str(Path(project.root).resolve()),
            permitted_worker_ids=list(dict.fromkeys(permitted_worker_ids)),
            required_validation_categories=list(dict.fromkeys(
                item.upper() for item in required_validation_categories
            )),
            plan_approvers=list(dict.fromkeys(plan_approvers)),
            promotion_approvers=list(dict.fromkeys(promotion_approvers)),
            actor_roles=actor_roles if actor_roles is not None else (current.actor_roles if current else {}),
            authority_mode=authority_mode or (current.authority_mode if current else "INDIVIDUAL_LOCAL"),
            authority_organization_id=(authority_organization_id if authority_organization_id is not None
                                       else (current.authority_organization_id if current else None)),
            authenticated_role_bindings=(authenticated_role_bindings
                if authenticated_role_bindings is not None
                else (current.authenticated_role_bindings if current else {})),
            approval_rules=approval_rules if approval_rules is not None else (
                current.approval_rules if current else ProjectGovernancePolicy(
                    project_id=project.id, project_root=str(Path(project.root).resolve())
                ).approval_rules
            ),
            artifact_validation_requirements={
                key.upper(): list(dict.fromkeys(item.upper() for item in values))
                for key, values in (
                    artifact_validation_requirements
                    if artifact_validation_requirements is not None
                    else (current.artifact_validation_requirements if current else {})
                ).items()
            },
            max_ticket_budget=max_ticket_budget,
            configured_by=actor.strip(),
            reason=reason.strip(),
            version=(current.version + 1) if current else 1,
            revision_history=list(current.revision_history) if current else [],
            updated_at=datetime.now(UTC),
        )
        self._validate_rules(policy)
        policy.revision_history.append(self._revision(policy))
        self.store.save_project_governance_policy(policy)
        return policy

    @staticmethod
    def binding(**values) -> str:
        encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def artifact_kinds(paths: list[str]) -> list[str]:
        mapping = {
            ".py": "PYTHON", ".pyi": "PYTHON", ".cpp": "CPP", ".cc": "CPP",
            ".cxx": "CPP", ".h": "CPP", ".hpp": "CPP", ".uasset": "UNREAL_ASSET",
            ".umap": "UNREAL_MAP", ".ini": "CONFIG", ".json": "CONFIG",
            ".uproject": "UNREAL_PROJECT", ".uplugin": "UNREAL_PLUGIN",
        }
        return sorted({mapping.get(Path(item).suffix.lower(), "FILE") for item in paths})

    @staticmethod
    def plan_binding(policy: ProjectGovernancePolicy, plan) -> tuple[str, str, str]:
        requirements_sha = ProjectGovernance.binding(
            validation_requirements=plan.validation_requirements,
            affected_paths=plan.affected_paths,
            steps=plan.steps,
            risks=plan.risks,
        )
        evidence_sha = ProjectGovernance.binding(
            evidence=[item.model_dump(mode="json") for item in plan.evidence]
        )
        binding = ProjectGovernance.binding(
            project_id=plan.project_id,
            project_root=ProjectGovernance.canonical_root(plan.project_root),
            artifact_id=plan.id,
            source_manifest_sha256=plan.final_manifest_sha256,
            requirements_sha256=requirements_sha,
            evidence_sha256=evidence_sha,
            policy_id=policy.id,
            policy_version=policy.version,
        )
        return binding, requirements_sha, evidence_sha

    @staticmethod
    def attempt_binding(
        policy: ProjectGovernancePolicy, attempt, patch_sha256: str
    ) -> tuple[str, str, str]:
        requirements_sha = ProjectGovernance.binding(
            decisions=[
                {
                    "id": item.id, "path": item.path, "artifact_kind": item.artifact_kind,
                    "category": item.category, "requirement": item.requirement,
                    "requires_unreal_editor": item.requires_unreal_editor,
                }
                for item in attempt.validation_decisions
            ]
        )
        evidence_sha = ProjectGovernance.binding(
            decisions=[
                {
                    "id": item.id, "status": item.status,
                    "worker_execution_id": item.worker_execution_id,
                    "external_report_id": item.external_report_id,
                    "evidence": [e.model_dump(mode="json") for e in item.evidence],
                }
                for item in attempt.validation_decisions
            ]
        )
        binding = ProjectGovernance.binding(
            project_id=attempt.project_id,
            project_root=ProjectGovernance.canonical_root(attempt.project_root),
            artifact_id=attempt.id,
            source_manifest_sha256=attempt.initial_manifest_sha256,
            patch_sha256=patch_sha256,
            requirements_sha256=requirements_sha,
            evidence_sha256=evidence_sha,
            policy_id=policy.id,
            policy_version=policy.version,
        )
        return binding, requirements_sha, evidence_sha

    def record_decisions(
        self,
        policy: ProjectGovernancePolicy,
        *,
        action: str,
        artifact_id: str,
        artifact_kinds: list[str],
        decision: str,
        actor: str,
        reason: str,
        binding_sha256: str,
        source_manifest_sha256: str | None = None,
        patch_sha256: str | None = None,
        requirements_sha256: str | None = None,
        evidence_sha256: str | None = None,
        identity: AuthenticatedIdentity | None = None,
    ) -> list[GovernanceDecision]:
        action, decision, actor, reason = action.upper(), decision.upper(), actor.strip(), reason.strip()
        if decision not in {"APPROVED", "DENIED"} or not actor or not reason:
            raise ValueError("Governance decisions require an actor, reason, and APPROVED or DENIED decision.")
        rules = self.rules(policy, action, artifact_kinds)
        if policy.authority_mode == "AUTHENTICATED_TEAM":
            if identity is None:
                raise ValueError("Team approval requires an authenticated, unexpired session.")
            if actor != identity.subject:
                raise ValueError("Actor label does not match the authenticated subject.")
            if identity.organization_id != policy.authority_organization_id:
                raise ValueError("Authenticated identity belongs to a different organization.")
            roles = policy.authenticated_role_bindings.get(identity.subject, [])
        else:
            roles = policy.actor_roles.get(actor, [])
        records = []
        for rule in rules:
            if rule.required_roles and not set(roles).intersection(rule.required_roles):
                continue
            records.append(GovernanceDecision(
                project_id=policy.project_id,
                project_root=policy.project_root,
                action=action,
                artifact_id=artifact_id,
                decision=decision,
                actor=actor,
                actor_roles=roles,
                authenticated_subject=identity.subject if identity else None,
                authentication_method=identity.authentication_method if identity else None,
                organization_id=identity.organization_id if identity else None,
                session_id=identity.session_id if identity else None,
                reason=reason,
                policy_id=policy.id,
                policy_version=policy.version,
                rule_id=rule.id,
                binding_sha256=binding_sha256,
                source_manifest_sha256=source_manifest_sha256,
                patch_sha256=patch_sha256,
                requirements_sha256=requirements_sha256,
                evidence_sha256=evidence_sha256,
            ))
        if not records:
            required = sorted({role for rule in rules for role in rule.required_roles})
            raise ValueError(
                "Actor lacks a role required by the applicable policy rules: "
                + ", ".join(required)
            )
        return records

    def evaluate(
        self,
        policy: ProjectGovernancePolicy,
        *,
        action: str,
        artifact_kinds: list[str],
        binding_sha256: str,
        history: list[GovernanceDecision],
    ) -> tuple[bool, list[str], list[str]]:
        missing: list[str] = []
        expired: list[str] = []
        for item in history:
            if item.action != action.upper():
                continue
            if item.policy_id != policy.id or item.policy_version != policy.version:
                expired.append(f"{item.id}: policy version changed")
            elif item.binding_sha256 != binding_sha256:
                expired.append(f"{item.id}: bound source, patch, requirements, or evidence changed")
        for rule in self.rules(policy, action, artifact_kinds):
            candidates = [
                item for item in history
                if item.action == action.upper()
                and item.rule_id == rule.id
                and item.decision == "APPROVED"
                and item.policy_id == policy.id
                and item.policy_version == policy.version
                and item.binding_sha256 == binding_sha256
            ]
            actors = {item.actor for item in candidates}
            if policy.authority_mode == "AUTHENTICATED_TEAM":
                candidates = [item for item in candidates if item.authenticated_subject == item.actor
                              and item.organization_id == policy.authority_organization_id
                              and item.authentication_method]
                actors = {item.authenticated_subject for item in candidates}
            if len(actors) < rule.minimum_approvals:
                missing.append(
                    f"{rule.id}: {rule.minimum_approvals - len(actors)} additional independent approval(s)"
                )
            for role in rule.required_roles:
                if not any(role in item.actor_roles for item in candidates):
                    missing.append(f"{rule.id}: reviewer role {role}")
        return not missing, missing, list(dict.fromkeys(expired))

    @staticmethod
    def rules(
        policy: ProjectGovernancePolicy, action: str, artifact_kinds: list[str]
    ) -> list[ApprovalPolicyRule]:
        kinds = {item.upper() for item in artifact_kinds}
        rules = [
            item for item in policy.approval_rules
            if item.action.upper() == action.upper()
            and (not item.artifact_kinds or kinds.intersection(item.artifact_kinds))
        ]
        if not rules:
            raise ValueError(f"Project policy has no rule for {action.upper()} decisions.")
        return rules

    @staticmethod
    def artifact_validation_categories(
        policy: ProjectGovernancePolicy, artifact_kinds: list[str]
    ) -> set[str]:
        required = set(policy.required_validation_categories)
        for kind in artifact_kinds:
            required.update(policy.artifact_validation_requirements.get(kind.upper(), []))
        for rule in ProjectGovernance.rules(policy, "PROMOTION", artifact_kinds):
            required.update(rule.required_validation_categories)
        return required

    def assert_budget(self, policy: ProjectGovernancePolicy, budget: TicketBudget) -> None:
        fields = (
            "max_tokens", "max_model_calls", "max_worker_calls",
            "max_wall_time_seconds", "max_branch_depth",
        )
        exceeded = [name for name in fields if getattr(budget, name) > getattr(policy.max_ticket_budget, name)]
        if exceeded:
            raise ValueError(
                "Policy rule BUDGET-CEILING denied: Ticket budget exceeds project policy: "
                + ", ".join(exceeded)
            )

    @staticmethod
    def assert_actor(allowed: list[str], actor: str, action: str) -> None:
        if "*" not in allowed and actor not in allowed:
            raise ValueError(
                f"Policy rule ACTOR-ALLOWLIST denied {action.lower()}: actor is not authorized."
            )

    @staticmethod
    def assert_worker(policy: ProjectGovernancePolicy, worker_id: str) -> None:
        if "*" not in policy.permitted_worker_ids and worker_id not in policy.permitted_worker_ids:
            raise ValueError(
                "Policy rule WORKER-ALLOWLIST denied: validation worker is not permitted."
            )

    @staticmethod
    def assert_required_validations(
        policy: ProjectGovernancePolicy, decisions, artifact_kinds: list[str] | None = None
    ) -> None:
        satisfied = {
            item.category.upper() for item in decisions
            if item.status in {"PASSED", "SATISFIED"}
        }
        required = ProjectGovernance.artifact_validation_categories(
            policy, artifact_kinds or [item.artifact_kind for item in decisions]
        )
        missing = sorted(required - satisfied)
        if missing:
            raise ValueError(
                "Policy rule REQUIRED-VALIDATION requires validation categories: "
                + ", ".join(missing)
            )

    def _validate_binding(self, policy: ProjectGovernancePolicy, project: ProjectRecord) -> None:
        if policy.project_id != project.id or self.canonical_root(policy.project_root) != self.canonical_root(project.root):
            raise ValueError("Project governance policy identity does not match its registered root.")

    @staticmethod
    def _validate_rules(policy: ProjectGovernancePolicy) -> None:
        if policy.authority_mode not in {"INDIVIDUAL_LOCAL", "AUTHENTICATED_TEAM"}:
            raise ValueError("Authority mode must be INDIVIDUAL_LOCAL or AUTHENTICATED_TEAM.")
        if policy.authority_mode == "AUTHENTICATED_TEAM":
            if not policy.authority_organization_id:
                raise ValueError("Authenticated team policy requires an organization identity.")
            if not policy.authenticated_role_bindings:
                raise ValueError("Authenticated team policy requires durable subject role bindings.")
        ids = [item.id for item in policy.approval_rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Project approval policy rule IDs must be unique.")
        for action in ("PLAN", "PROMOTION", "ATTESTATION"):
            if not any(item.action.upper() == action for item in policy.approval_rules):
                raise ValueError(f"Project policy requires at least one {action} rule.")

    @staticmethod
    def _revision(policy: ProjectGovernancePolicy) -> ProjectPolicyRevision:
        return ProjectPolicyRevision(
            version=policy.version,
            permitted_worker_ids=policy.permitted_worker_ids,
            required_validation_categories=policy.required_validation_categories,
            plan_approvers=policy.plan_approvers,
            promotion_approvers=policy.promotion_approvers,
            actor_roles=policy.actor_roles,
            authority_mode=policy.authority_mode,
            authority_organization_id=policy.authority_organization_id,
            authenticated_role_bindings=policy.authenticated_role_bindings,
            approval_rules=policy.approval_rules,
            artifact_validation_requirements=policy.artifact_validation_requirements,
            max_ticket_budget=policy.max_ticket_budget.model_dump(),
            configured_by=policy.configured_by,
            reason=policy.reason,
            created_at=policy.updated_at,
        )
