# Security model

This document describes implemented controls and known limits. It is not a production-readiness
claim. The reproducible platform baseline remains Windows 11/`windows-latest`; WSL2 is claimed only
inside the narrow Milestone 14 live proof. Neo4j behavior is serialization-contract tested, not a
deployed security proof. Linux and macOS are not currently supported-platform claims.

## Threat model

| Threat | Boundary and required behavior | Remaining limitation |
|---|---|---|
| Malicious repository instructions | Repository text is untrusted data. It grants no authority and must not change policy, worker limits, approvals, tickets, or prompts treated as system instructions. | No claim is made that a model will always disregard adversarial prose; enforcement must remain outside the model. |
| Links and path aliases | Every existing component is checked with `lstat`; symlinks and Windows reparse points, including junctions, are rejected before canonical confinement. Registered roots may not overlap. | Network filesystems and platform-specific alias mechanisms outside the Windows baseline are unproved. |
| Ignored/generated files | Git ignore status is not authorization. Plans and promotions bind explicit path and byte manifests; unexpected generated output fails the changed-path boundary. | Tool-specific generated-file semantics remain experimental. |
| Secrets/credentials | Worker environments use an allowlist and reject credential-like additions. Source and exported evidence must not intentionally contain secrets. | There is no general secret scanner; a secret already committed to source can still be read within authorized scope. |
| Subprocess execution | Only configured executables, argument templates, paths, process/time/memory/output limits, and confined worker routes may run. Repository instructions cannot authorize a process. | OS sandbox strength is limited to the documented worker/platform evidence. |
| Network egress | Default confined workers have no network authority; egress requires a separately configured worker policy. | Host firewall enforcement is not independently proved on every intended platform. |
| Dependency execution | Installation/build scripts are executable code and belong to controlled-execution risk tier. Locked dependencies do not by themselves authorize installation inside a project. | Supply-chain provenance and package signatures are not comprehensively verified. |
| Audit tampering | Audit packages can carry an HMAC-SHA256 authentication tag rooted in a managed installation key. The ordinary `sha256` field remains explicitly only a checksum. | The symmetric trust anchor is not public-key non-repudiation or external transparency. |
| Identity spoofing | `AUTHENTICATED_TEAM` decisions require a valid signed, unexpired session; its subject and organization must match durable role bindings. Display names, organization labels, and supplied roles are ignored for authorization. | The implemented identity provider is installation-local; enterprise SSO, MFA, and external lifecycle integration are unavailable. |
| Cross-scope access | Policy binds exact project ID and canonical root; authenticated team policy also binds an organization ID. | An independent external penetration test has not occurred. |

## Proportionate governance

Risk tiers are: **0 read-only**, **1 controlled execution**, **2 project mutation**, and **3
recovery/policy administration**. Tier 0 does not require mutation-level approval. Tier 1 requires
the bounded worker policy and any rule-specific execution decision. Tier 2 requires separately
bound promotion approval. Tier 3 requires explicit administrator authority and confirmation.
Observer states the current authority mode, consequence, and required decision. AI ideas remain
untrusted opt-in candidates with no ticket, run, approval, or write authority.

## Approval binding and invalidation

Every governance decision retains the rule, policy ID/version, source manifest, patch,
requirements, evidence, actor attribution, and—when in team mode—the authenticated subject,
organization, authentication method, and session ID. A policy-version mismatch reports that the
policy changed. A binding mismatch reports that bound source, patch, requirements, or evidence
changed. Neither case silently reuses the earlier decision.

## Managed-key trust model and operations

`ManagedKeyring` creates 256-bit random keys with exclusive file creation and owner-only POSIX mode
where supported. The key file must live outside registered projects and source control, with host
account and backup encryption protecting it. Rotation makes a new active key and retains the prior
key for verification. Revocation immediately makes packages and sessions from that key fail and
also rotates an active revoked key. Verification fails closed for missing, unknown, revoked, or
algorithm-mismatched keys and for changed bytes.

Backups contain signing capability and must be encrypted and access-controlled. `backup` refuses
overwrite; `restore` validates structure and refuses to replace an existing keyring. Test restore
into an isolated installation, verify retained packages, then securely retire the test copy.
Loss of every key copy makes prior authenticated packages unverifiable; restore never treats their
ordinary checksum as authentication. Compromise requires revocation, rotation, investigation, and
re-export/re-signing where policy permits—never silent re-signing of historical evidence.
