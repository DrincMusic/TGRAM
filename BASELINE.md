# Development baseline

TGRAM is a local application. The development baseline is Windows, Python 3.12,
Node.js 24.11.1, and npm 10. Follow README.md for installation and startup.

Install requirements-dev.lock and dashboard/package-lock.json before checking changes.
Run scripts/verify.ps1 for Python lint/tests and frontend lint/build/tests. Browser
checks require Playwright and its browser installation. Model evaluations are opt-in
and use the operator's own configured provider; they are not required for unit tests.

Tests construct small synthetic repositories under temporary directories. These are
fixtures for general project behavior, not copies of anyone's connected projects.
Local profiles, credentials, conversations, learned documents, database files, and
execution artifacts are excluded from source control.

This is an experimental release. Passing tests does not establish production safety
or independent verification of model-generated facts.
