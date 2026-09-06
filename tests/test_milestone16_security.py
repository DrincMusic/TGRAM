from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rlmgraph.authority import ManagedKeyring, SessionAuthority
from rlmgraph.governance import ProjectGovernance
from rlmgraph.models import ApprovalPolicyRule, ProjectGovernancePolicy
from rlmgraph.operations import TicketAuditExporter
from rlmgraph.security import RiskTier, confined_path, explain_risk, sanitized_environment


def team_policy() -> ProjectGovernancePolicy:
    return ProjectGovernancePolicy(
        project_id="P1", project_root="C:/project", authority_mode="AUTHENTICATED_TEAM",
        authority_organization_id="ORG-A", authenticated_role_bindings={"subject-1": ["REVIEWER"]},
        approval_rules=[ApprovalPolicyRule(id="R", action="PLAN", required_roles=["REVIEWER"])],
    )


def test_actor_and_role_strings_cannot_approve_in_team_mode(tmp_path: Path) -> None:
    governance = ProjectGovernance(None)
    with pytest.raises(ValueError, match="authenticated"):
        governance.record_decisions(team_policy(), action="PLAN", artifact_id="A", artifact_kinds=[],
                                    decision="APPROVED", actor="subject-1", reason="reviewed",
                                    binding_sha256="b")

    authority = SessionAuthority(ManagedKeyring(tmp_path / "keys.json"))
    wrong_org = authority.authenticate(authority.issue("subject-1", "ORG-B"))
    with pytest.raises(ValueError, match="different organization"):
        governance.record_decisions(team_policy(), action="PLAN", artifact_id="A", artifact_kinds=[],
                                    decision="APPROVED", actor="subject-1", reason="reviewed",
                                    binding_sha256="b", identity=wrong_org)


def test_authenticated_decision_retains_identity_and_rejects_expiration(tmp_path: Path) -> None:
    authority = SessionAuthority(ManagedKeyring(tmp_path / "keys.json"))
    token = authority.issue("subject-1", "ORG-A", ttl_seconds=1)
    identity = authority.authenticate(token)
    decision = ProjectGovernance(None).record_decisions(
        team_policy(), action="PLAN", artifact_id="A", artifact_kinds=[], decision="APPROVED",
        actor="subject-1", reason="reviewed", binding_sha256="b", identity=identity)[0]
    assert decision.authenticated_subject == "subject-1"
    assert decision.organization_id == "ORG-A"
    with pytest.raises(ValueError, match="expired"):
        authority.authenticate(token, now=datetime.now(UTC) + timedelta(seconds=2))


def test_audit_authentication_detects_tampering_rotation_revocation_and_missing_key(tmp_path: Path) -> None:
    ring = ManagedKeyring(tmp_path / "keys.json")
    canonical = b'{"ticket":"T"}'
    signature = ring.sign("RLMGRAPH_AUDIT_V1", canonical)
    assert ring.verify("RLMGRAPH_AUDIT_V1", canonical, signature)[0]
    assert not ring.verify("RLMGRAPH_AUDIT_V1", canonical + b"x", signature)[0]
    old = signature["key_id"]
    ring.rotate()
    assert ring.verify("RLMGRAPH_AUDIT_V1", canonical, signature)[0]
    ring.revoke(old, "suspected compromise")
    assert ring.verify("RLMGRAPH_AUDIT_V1", canonical, signature) == (False, "signing key is revoked")
    assert not TicketAuditExporter.verify({"sha256": "ordinary-checksum"}, ring, require_authenticated=True)


def test_path_link_secret_and_risk_boundaries(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    file = root / "safe.txt"
    file.write_text("safe")
    assert confined_path(root, "safe.txt") == file
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    try:
        (root / "link").symlink_to(outside)
    except OSError:
        pass
    else:
        with pytest.raises(ValueError, match="link or reparse"):
            confined_path(root, "link")
    monkeypatch.setenv("SERVICE_TOKEN", "secret")
    assert "SERVICE_TOKEN" not in sanitized_environment()
    with pytest.raises(ValueError, match="Credential-like"):
        sanitized_environment({"API_KEY": "secret"})
    assert explain_risk("VIEW").tier is RiskTier.READ_ONLY
    assert explain_risk("PROMOTION").tier is RiskTier.PROJECT_MUTATION
