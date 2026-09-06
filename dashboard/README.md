# TGRAM conversation and RLMGraph Observer

The Overview includes direct conversation, a selector for saved conversations, and a searchable
conversation-memory library. Expand a memory to see its original user message and later correction.
“Discuss a correction” opens a draft in its source conversation; send the completed correction and
check the library to confirm what was recorded. It is not a direct database edit.

To start work, select a project and say “start working on [outcome]”, or say
“start working on [outcome] in project [name or ID]”. You can also ask “Can you fix [problem]?”,
start an existing ticket by exact ID, or say “start this task” for the selected ticket.
“Task status” follows the last task in this conversation. “Open task and progress” opens its ticket.
Protected projects start investigation/planning and require plan approval before implementation.
Existing autonomous modes run only the requested ticket under that project's current permissions.
Chat does not change execution mode or authorize the rest of the queue. Focused new task outcomes
are limited to 500 characters and use the existing default ticket budget.

New responses retain a compact memory receipt containing references, not duplicate memory bodies.
“Memory behind this response” distinguishes supplied facts from facts the responder reported citing.
Older responses without receipts say so explicitly. Technical routes and project evidence remain
available under “Response details and evidence.”

Local live observability for RLMGraph's Neo4j task, claim, evidence, multi-claim conflict cluster,
and resolution graph. Cluster cards show every interpretation, corroborated claims, outliers, and
the selected adjudication or explicit unresolved status.
Claim inspection answers “why do we believe this?” with source hashes and lines, producing task and
adapter, derived claims, Git state, validity transitions, and supersession history.
Reconstruction cards compare the selected context with a fixed-neighborhood baseline. Every seed,
expansion, and prune decision is selectable, with its relation, rationale, score, and token cost.

The dashboard runs locally because its companion service reads local project state and invokes
configured model providers. SQLite is the default and does not require Docker. Set
`RLMGRAPH_BACKEND=neo4j` explicitly to use the optional Neo4j container. From the repository root, use:

```powershell
.\examples\run_dashboard.ps1
```

The page is available at `http://localhost:3000`. The observer API binds to
`http://127.0.0.1:8787`. The launcher checks both services before opening the page.

Use your existing local profile to access conversations. Model provider settings remain under
the account controls. A model-provider failure is a conversation error, not a verified answer.
