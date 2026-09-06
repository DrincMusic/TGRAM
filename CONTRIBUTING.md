# Contributing to TGRAM

Use the setup in README.md. Keep changes focused and explain the user-visible problem,
the resulting behavior, and how it was checked. Include provenance when adding sourced material.
Contributions intended for inclusion use the repository's Apache-2.0 license unless explicitly
stated otherwise; do not submit material you lack permission to distribute.

Run focused Python checks with `.\.venv\Scripts\python.exe -m pytest -q tests/<test_file>.py`
and `npm --prefix dashboard run test:source` for dashboard source changes.
The full gate is `.\scripts\verify.ps1`; it also builds and exercises the dashboard.
Pytest removes successful and failed temporary test directories at session end to limit storage.

Live model evaluations are separate, opt-in work and consume the signed-in account's allowance.
Do not require credentials or a live model for ordinary unit tests. Keep generated databases,
learned documents, conversation histories, signing keys, and local evidence out of pull requests.
Preserve project boundaries and explicit plan/promotion approvals.

For a security issue, use GitHub's private vulnerability reporting if enabled on the published
repository. Do not put credentials or private conversation data in a public issue. If private
reporting is unavailable, request a private contact without disclosing the exploit or secret.
