# TGRAM (RLMGraph)

TGRAM is an experimental local application for persistent conversational memory, sourced learning,
and governed work on connected code projects. The Python package and command remain `rlmgraph`.
The interface supports conversation, memory inspection, document learning, and ticket review.

## Start here

The supported development baseline is Windows with Python 3.12 and Node.js 24.11.1
(npm 10). Install Codex CLI separately and sign in using `codex login` with your ChatGPT
account. Select the Codex CLI provider and a model available to your account in TGRAM's
model settings; this route does not require an API key.

From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
npm --prefix dashboard ci
.\examples\run_dashboard.ps1
```

Open `http://localhost:3000`, create or select a local profile, configure the model provider,
and connect a project. SQLite is the default; Docker and Neo4j are optional.
Read [the interface guide](dashboard/README.md) and [security boundaries](SECURITY.md)
before enabling work on a project.

Document learning stores source-backed statements, quotations, and applicability limits.
Source support is not independent proof of truth. Retrieval uses deterministic matching with
experimental neural ranking; improved neural retrieval has not been established. Projects are connected explicitly by each installation. No connected project or learned
document is bundled with this release.

## License and contributions

TGRAM's original source is licensed under the [Apache License 2.0](LICENSE).
Dependencies and separately supplied documents retain their own licenses.
See [CONTRIBUTING.md](CONTRIBUTING.md) for development checks.

TGRAM keeps conversations and learned facts locally. Review sources and proposed changes before
approving project work. This is an experimental release.
