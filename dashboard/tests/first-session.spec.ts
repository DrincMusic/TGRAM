import { expect, test, type Page } from "@playwright/test";

const testProfile = { id: "test-profile", name: "Test user", owns_legacy_memory: true };
const modelSettings = { roles: [], available_models: [], providers: {} };

test.beforeEach(async ({ page }) => {
  await page.addInitScript((profile) => {
    sessionStorage.setItem("tgram-profile-session", JSON.stringify({ profile, token: "test-only-session" }));
  }, testProfile);
});

const project = {
  id: "P1",
  node_type: "project",
  kind: "PROJECT",
  title: "checkout-pilot",
  status: "COMPLETED",
  root: "C:\\disposable\\checkout-pilot",
  explicitly_selected: true,
  read_only: true,
};
const criterion = {
  id: "C1",
  description: "Orders of $50 receive free shipping",
  status: "PENDING",
  evidence_ids: [],
};
const ticket = {
  id: "T1",
  node_type: "ticket",
  kind: "TICKET",
  project_id: "P1",
  title: "Free shipping at $50",
  description: "Orders of $50 or more should receive free shipping.",
  status: "ACTIVE",
  priority: "MEDIUM",
  created_at: "2026-08-16T12:00:00Z",
  ticket_criteria: [criterion],
  ticket_constraints: [],
  ticket_budget: {
    max_tokens: 50000,
    max_model_calls: 10,
    max_worker_calls: 10,
    max_wall_time_seconds: 900,
    max_branch_depth: 4,
  },
  ticket_usage: {
    tokens: 0,
    model_calls: 0,
    worker_calls: 0,
    wall_time_seconds: 0,
    deepest_branch: 0,
  },
  closure_ready: false,
  closure_failures: ["Acceptance criterion is unresolved."],
  closure_gates: [
    {
      criterion_id: "C1",
      description: criterion.description,
      status: "PENDING",
      resolved: false,
      explanation: "No current evidence.",
      evidence_assessments: [],
    },
  ],
  eligible_ticket_evidence: [],
  ineligible_ticket_evidence: [],
};
const plan = {
  id: "PLAN1",
  node_type: "project_workspace_result",
  kind: "CHANGE_PLAN",
  title: "Plan",
  status: "COMPLETED",
  ticket_id: "T1",
  project_id: "P1",
  project_name: "checkout-pilot",
  prompt: ticket.description,
  answer: "Update the shipping threshold and verify boundary cases.",
  affected_paths: ["checkout/pricing.py", "tests/test_pricing.py"],
  approval_status: "PENDING",
  approval_history: [],
  approval_missing: ["one reviewer"],
  approval_expiration_reasons: [],
  workspace_steps: ["Update the threshold comparison.", "Add boundary tests."],
};
const attempt = {
  id: "A1",
  node_type: "implementation_sandbox",
  kind: "IMPLEMENTATION_SANDBOX",
  title: "Validated proposal",
  status: "READY_FOR_REVIEW",
  ticket_id: "T1",
  project_id: "P1",
  plan_record_id: "PLAN1",
  changes: [
    {
      path: "checkout/pricing.py",
      unified_diff: "- total > 50\n+ total >= 50",
      before_hash: "a",
      after_hash: "b",
    },
  ],
  validations: [
    {
      command: ["pytest", "-q"],
      exit_code: 0,
      stdout: "8 passed",
      stderr: "",
      duration_ms: 100,
    },
  ],
  validation_decisions: [
    {
      id: "V1",
      path: "checkout/pricing.py",
      artifact_kind: "PYTHON_SOURCE",
      category: "PYTEST",
      requirement: "Tests pass",
      status: "PASSED",
      requires_unreal_editor: false,
      execution_index: 0,
      evidence: [],
    },
  ],
  promotion_approval: null,
  promotion_approval_history: [],
  promotion_approval_missing: [],
  promotion_approval_expiration_reasons: [],
  filesystem_disposed: true,
  original_unchanged: true,
  failure_reason: null,
};
const appliedPromotion = {
  id: "PROMO1",
  approval_id: "PA1",
  status: "COMPLETED",
  initial_manifest_sha256: "before",
  applied_manifest_sha256: "after",
  final_manifest_sha256: "after",
  validations: [],
  rollback_validations: [],
  rollback_verified: null,
  failure_reason: null,
  lease_id: null,
  fencing_token: null,
  evidence: [],
  checkpoints: [],
  mutation_journal: null,
  reconciliation: null,
  completed_at: "2026-08-16T12:05:00Z",
};
const projectOption = {
  id: "P1",
  name: "checkout-pilot",
  root: project.root,
  organization: "Personal",
  execution_mode: "PROTECTED",
  project_goals: [],
  ideas: [] as {
    id: string;
    title: string;
    detail: string;
    status: string;
    created_at: string;
  }[],
  read_only: true,
  write_capability: false,
  index_current: true,
  index_scan_id: "S1",
  artifact_count: 4,
  dependency_count: 2,
  adapter: "SOURCE_GRAPH",
};

type State = {
  nodes: Record<string, unknown>[];
  edges: unknown[];
  workspace: Record<string, unknown>;
  generated_at: string;
  connected: boolean;
  running: boolean;
  root_status: string;
  metrics: Record<string, unknown>;
};
function base(nodes: Record<string, unknown>[] = []): State {
  return {
    generated_at: "2026-08-16T12:00:00Z",
    connected: true,
    running: false,
    root_status: "READY",
    nodes,
    edges: [],
    metrics: {
      tasks: 0,
      codex_calls: 0,
      resolution_attempts: 0,
      evidence_claims: 0,
      average_evidence_confidence: null,
      active_tasks: 0,
      stopped_tasks: 0,
      onboarded_projects: nodes.some((n) => n.node_type === "project") ? 1 : 0,
    },
    workspace: {
      focus_ticket_id: nodes.some((n) => n.node_type === "ticket")
        ? "T1"
        : null,
      needs_attention: 0,
      in_progress: 0,
      completed: 0,
      work_items: nodes.some((n) => n.node_type === "ticket")
        ? [
            {
              ticket_id: "T1",
              project_id: "P1",
              title: ticket.title,
              priority: "MEDIUM",
              status: "ACTIVE",
              action: "INVESTIGATE",
              action_label: "Generate ticket impact plan",
              detail: "No plan exists yet.",
              urgency: "NORMAL",
              closure_ready: false,
              resolved_criteria: 0,
              total_criteria: 1,
              exhausted_budgets: [],
              updated_at: "2026-08-16T12:00:00Z",
            },
          ]
        : [],
      durable_activities: [],
      scheduled_work: [],
      governance_policies: [],
      leases: [],
    },
  };
}

async function mockApi(page: Page, initial = base()) {
  let state = structuredClone(initial);
  const ticketCreateBodies: Record<string, unknown>[] = [];
  let projects = state.nodes.some((n) => n.node_type === "project")
    ? [projectOption]
    : [];
  await page.route("http://127.0.0.1:8787/api/**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname;
    if (path === "/api/profiles") return route.fulfill({ json: { profiles: [testProfile] } });
    if (path === "/api/profiles/me") return route.fulfill({ json: { profile: testProfile } });
    if (path === "/api/models") return route.fulfill({ json: modelSettings });
    if (req.method() === "GET" && path === "/api/snapshot")
      return route.fulfill({ json: state });
    if (req.method() === "GET" && path === "/api/workspace/options")
      return route.fulfill({
        json: {
          projects,
          limits: {
            request_characters: 1000,
            acceptance_criteria: 10,
            criterion_characters: 500,
            concurrent_jobs: 1,
            project_writes: 0,
            unreal_launches: 0,
            compilations: 0,
          },
        },
      });
    if (req.method() === "GET" && path === "/api/diagnostics/options")
      return route.fulfill({
        json: {
          project_root: project.root,
          read_only: true,
          tests: [],
          limits: {
            question_characters: 500,
            dependency_files: 5,
            concurrent_runs: 1,
            wall_time_seconds: 60,
            model_calls: 1,
            project_writes: 0,
          },
        },
      });
    if (req.method() === "GET" && path === "/api/chat/sessions")
      return route.fulfill({ json: { sessions: [] } });
    if (path === "/api/tickets/export")
      return route.fulfill({
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          format_version: 1,
          ticket_id: "T1",
          verified: true,
        }),
      });
    const body = req.postDataJSON?.() || {};
    if (path === "/api/chat") {
      return route.fulfill({
        json: {
          answer: "The current implementation overweights workflow infrastructure relative to recursive investigation.",
          session_id: "CHAT1",
          route: "NEW_INVESTIGATION",
          operation_route: "FRESH_INVESTIGATION",
          scope: "SYSTEM",
          investigation_mode: "RECURSIVE",
          routing_confidence: 0.98,
          routing_reason: "The question explicitly names RLMGraph.",
          confidence: 0.87,
          task_id: "TASK1",
          claim_id: "CLAIM1",
          work_project_id: "P1",
          evidence: [],
          task_tree: [],
          context_claim_ids: [],
          context_token_estimate: 0,
        },
      });
    }
    if (path === "/api/projects/browse") {
      return route.fulfill({
        json: { root: project.root, cancelled: false },
      });
    }
    if (path === "/api/projects/connect") {
      projects = [projectOption];
      state = base([project]);
      return route.fulfill({
        status: 201,
        json: {
          project,
          scan: { status: "COMPLETED", read_only_verified: true },
        },
      });
    }
    if (path === "/api/projects/organization") {
      projects = projects.map((item) =>
        item.id === body.project_id
          ? { ...item, organization: String(body.organization) }
          : item,
      );
      return route.fulfill({ json: projects[0] });
    }
    if (path === "/api/projects/ideas/suggest") {
      return route.fulfill({
        json: {
          project_id: "P1",
          project_name: "checkout-pilot",
          index_scan_id: "S1",
          indexed_manifest_sha256: "manifest-1",
          source_integrity_verified: true,
          read_only_verified: true,
          suggestions: [
            {
              title: "Explain the shipping threshold",
              detail: "Show the boundary where a user makes the decision.",
              rationale: "The threshold currently appears only in code.",
              evidence: [
                {
                  path: "checkout/pricing.py",
                  line: 12,
                  detail: "return total >= 50",
                },
              ],
            },
          ],
          confidence: 0.91,
          files_examined: ["checkout/pricing.py"],
          worker: {
            name: "Codex CLI",
            model: "fixture-model",
            sandbox: "read-only",
            calls: 1,
            indexed_files: 4,
            authorized_files: 4,
            source_bytes: 2048,
            monetary_cost: null,
            cost_basis:
              "Codex CLI account-backed execution; monetary cost is not exposed.",
          },
          persistence: "NOT_SAVED",
          authority: "NO_TICKET_RUN_OR_PROJECT_WRITE",
        },
      });
    }
    if (path === "/api/projects/ideas") {
      const idea = {
        id: `I${projects.flatMap((item) => item.ideas).length + 1}`,
        title: String(body.title),
        detail: String(body.detail),
        status: "DRAFT" as const,
        created_at: "2026-08-16T12:00:00Z",
      };
      projects = projects.map((item) =>
        item.id === body.project_id
          ? { ...item, ideas: [...item.ideas, idea] }
          : item,
      );
      return route.fulfill({ status: 201, json: idea });
    }
    if (path === "/api/projects/ideas/status") {
      projects = projects.map((item) =>
        item.id === body.project_id
          ? {
              ...item,
              ideas: item.ideas.map((idea) =>
                idea.id === body.idea_id
                  ? { ...idea, status: String(body.status) }
                  : idea,
              ),
            }
          : item,
      );
      return route.fulfill({ json: projects[0] });
    }
    if (path === "/api/tickets/create") {
      ticketCreateBodies.push(body);
      state = base([
        project,
        { ...ticket, title: body.title, description: body.description },
      ]);
      return route.fulfill({ status: 201, json: ticket });
    }
    if (path === "/api/workspace/plan") {
      state = base([project, ticket, plan]);
      return route.fulfill({ status: 202, json: {} });
    }
    if (path === "/api/tickets/approve-plan") {
      state = base([
        project,
        ticket,
        { ...plan, approval_status: body.decision, approval_missing: [] },
      ]);
      return route.fulfill({ json: {} });
    }
    if (path === "/api/sandboxes/start") {
      state = base([
        project,
        ticket,
        { ...plan, approval_status: "APPROVED", approval_missing: [] },
        attempt,
      ]);
      return route.fulfill({ status: 202, json: {} });
    }
    if (path === "/api/sandboxes/approve-promotion") {
      state = base([
        project,
        ticket,
        plan,
        {
          ...attempt,
          promotion_approval: { decision: body.decision },
          promotion_approval_history: [],
        },
      ]);
      return route.fulfill({ json: {} });
    }
    if (path === "/api/sandboxes/promote") {
      state = base([
        project,
        ticket,
        plan,
        {
          ...attempt,
          status: "PROMOTED",
          promotion_approval: { decision: "APPROVED" },
          promotion: appliedPromotion,
        },
      ]);
      return route.fulfill({ json: {} });
    }
    if (path === "/api/sandboxes/reconcile") {
      const done = {
        ...ticket,
        closure_ready: true,
        closure_failures: [],
        ticket_criteria: [{ ...criterion, status: "EVIDENCED" }],
        closure_gates: [
          {
            ...ticket.closure_gates[0],
            resolved: true,
            status: "EVIDENCED",
            explanation: "Current validation supports this criterion.",
          },
        ],
      };
      state = base([
        project,
        done,
        plan,
        {
          ...attempt,
          status: "PROMOTED",
          promotion: {
            ...appliedPromotion,
            reconciliation: { status: "COMPLETED" },
          },
        },
      ]);
      return route.fulfill({ json: {} });
    }
    if (path === "/api/tickets/transition") {
      const current =
        state.nodes.find((n) => n.node_type === "ticket") || ticket;
      state.nodes = state.nodes.map((n) =>
        n.node_type === "ticket"
          ? {
              ...current,
              status: body.status,
              closure_ready: true,
              closure_failures: [],
            }
          : n,
      );
      return route.fulfill({ json: {} });
    }
    if (path.endsWith("/resume")) {
      (state.workspace.durable_activities as unknown[]) = [];
      return route.fulfill({ status: 202, json: {} });
    }
    return route.fulfill({ status: 200, json: {} });
  });
  return {
    get: () => state,
    set: (next: State) => {
      state = structuredClone(next);
    },
    setProjects: (next: typeof projects) => {
      projects = next;
    },
    ticketCreateBodies,
  };
}

test("self-investigation requires explicit user direction before creating governed work", async ({
  page,
}) => {
  const ctl = await mockApi(page, base([project]));
  await page.goto("/");
  await page.getByLabel("Message").fill("Where has RLMGraph development gone wrong?");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText(/overweights workflow infrastructure/)).toBeVisible();
  await page.locator(".chat-message.assistant").getByText("Response details and evidence").click();
  await expect(page.getByText("Evidence scope: SYSTEM")).toBeVisible();
  expect(ctl.ticketCreateBodies).toHaveLength(0);

  const objective = "Make self-investigation help users decide what to change next.";
  const acceptanceCriterion =
    "A user can trace every proposed change to a verified claim and explicitly approve it.";
  await page
    .getByRole("button", { name: "Create user-directed ticket from claim" })
    .click();
  await page.getByLabel("Outcome for the person using RLMGraph").fill(objective);
  await page.getByLabel("Observable acceptance criterion").fill(acceptanceCriterion);
  expect(ctl.ticketCreateBodies).toHaveLength(0);
  await page.getByRole("button", { name: "Create governed draft ticket" }).click();

  await expect(page.getByRole("tab", { name: /Tickets/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(ctl.ticketCreateBodies).toHaveLength(1);
  expect(ctl.ticketCreateBodies[0]).toMatchObject({
    project_id: "P1",
    source_claim_ids: ["CLAIM1"],
    acceptance_criteria: [acceptanceCriterion],
  });
  expect(String(ctl.ticketCreateBodies[0].description)).toContain(
    objective,
  );
});

test("complete workflow remains direct navigation, transparent, keyboard operable, and persistent", async ({
  page,
}) => {
  const ctl = await mockApi(page);
  await page.goto("/");
  await expect(page.getByRole("tab", { name: /Overview/ })).toBeVisible();
  await expect(page.getByText("No local project is connected.")).toBeVisible();
  await page.getByRole("tab", { name: /Projects/ }).click();
  await expect(
    page.getByRole("group", { name: "Selected project" }),
  ).toBeVisible();
  await expect(
    page.getByRole("group", { name: "Selected ticket" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "New ticket" })).toHaveCount(0);
  await expect(page.getByLabel("Active work context")).toContainText(
    "No project selected",
  );
  await expect(
    page.getByText(/selected folder becomes the boundary/i),
  ).toBeVisible();
  await page.getByRole("button", { name: "Browse for project folder" }).click();
  await expect(page.getByLabel("Folder path")).toHaveValue(project.root);
  await expect(page.getByRole("status")).toContainText(
    "Nothing has been read or connected yet",
  );
  await page.getByRole("button", { name: "Connect existing project" }).press("Enter");
  await expect(page.getByRole("status")).toContainText("indexed read-only");
  await page.getByRole("tab", { name: /Tickets/ }).click();
  const create = page.locator(".ticket-create");
  await create.locator("summary").first().click();
  await create.getByText("Limits and defaults").click();
  await expect(create).toContainText(
    "implementation runs in an isolated copy; applying reviewed files requires a separate approval",
  );
  await create.getByLabel("Title").fill(ticket.title);
  await create.getByLabel("Requested outcome").fill(ticket.description);
  await create.getByLabel(/Acceptance criteria/).fill(criterion.description);
  await create.getByRole("button", { name: "Create ticket" }).click();
  await expect(page.getByLabel("Active work context")).toContainText(
    ticket.title,
  );
  const next = page.getByRole("region", { name: "Next ticket step" });
  await next.getByRole("button", { name: "Create plan" }).click();
  await next.getByRole("button", { name: "Read proposed plan" }).click();
  await next.getByRole("button", { name: "Approve plan", exact: true }).click();
  await expect(next).toContainText("Step 3");
  await next.getByRole("button", { name: "Start implementation in isolated copy" }).click();
  await next.getByRole("button", { name: "Review changes and validation" }).click();
  await page.getByRole("button", { name: "Approve and apply change" }).click();
  await expect(page.getByRole("status")).toContainText("Approved files applied");
  await page.getByRole("button", { name: "Refresh project index", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Project index refreshed");
  await next.getByRole("button", { name: "Mark task satisfied" }).click();
  await next.getByRole("button", { name: "Close ticket" }).click();
  await expect.poll(() => ctl.get().nodes.find((node) => node.id === ticket.id)?.status).toBe("CLOSED");
  await expect(next).toHaveCount(0);
  await page.reload();
  await page.getByRole("tab", { name: /Tickets/ }).click();
  await expect(next).toHaveCount(0);
});

test("plan and apply rejections are distinct and do not expose an apply action", async ({
  page,
}) => {
  const ctl = await mockApi(page, base([project, ticket, plan]));
  await page.goto("/");
  await page.getByRole("tab", { name: /Tickets/ }).click();
  await page.getByRole("button", { name: /Plan and implementation/ }).click();
  await page.getByRole("button", { name: "Read proposed plan" }).click();
  await page.locator(".ticket-next-step").getByRole("button", { name: "Reject plan", exact: true }).click();
  await page.getByLabel("Why should the plan change?").fill("Revision required.");
  await page.getByRole("button", { name: "Record rejection" }).click();
  expect((ctl.get().nodes.at(-1) as typeof plan).approval_status).toBe(
    "DENIED",
  );
  ctl.set(base([project, ticket, plan, attempt]));
  await page.reload();
  await page.getByRole("tab", { name: /Tickets/ }).click();
  await page.getByRole("button", { name: /Plan and implementation/ }).click();
  await page.getByRole("button", { name: "Reject change" }).click();
  expect((ctl.get().nodes.at(-1) as typeof attempt).promotion_approval).toEqual(
    { decision: "DENIED" },
  );
  await expect(
    page.getByRole("button", { name: "Apply approved change" }),
  ).toHaveCount(0);
});

test("projects manage durable manifests, ideas, and local organizations", async ({
  page,
}) => {
  await mockApi(page, base([project]));
  await page.goto("/");
  await page.getByRole("tab", { name: /Projects/ }).click();

  await expect(
    page.getByRole("heading", { name: "Project manifest, goals, ideas, and organizations" }),
  ).toBeVisible();
  await expect(page.getByLabel("Project index metadata")).toContainText("Read-only index");
  await expect(page.locator(".manifest-location")).toContainText(project.root);

  await page.getByLabel("Project document").selectOption("ideas");
  await page.getByRole("button", { name: "Suggest ideas" }).click();
  await expect(
    page.getByRole("heading", { name: "Explain the shipping threshold" }),
  ).toBeVisible();
  await expect(page.locator(".idea-suggestion-provenance")).toContainText(
    "fixture-model",
  );
  await expect(page.locator(".idea-suggestion-provenance")).toContainText(
    "not saved",
  );
  await expect(page.getByText("checkout/pricing.py:12")).toBeVisible();
  await expect(page.getByRole("tab", { name: /Tickets/ })).toContainText("0");
  await page.getByRole("button", { name: "Save suggestion" }).click();
  await expect(page.getByRole("button", { name: "Saved" })).toBeDisabled();
  await expect(page.getByRole("status")).toContainText(
    "No ticket or run was created",
  );
  await page
    .getByLabel("Idea", { exact: true })
    .fill("Clarify shipping thresholds");
  await page
    .getByLabel("Notes")
    .fill("Keep the boundary visible in ordinary product language.");
  await page.getByRole("button", { name: "Save idea" }).click();
  await expect(page.getByText("Clarify shipping thresholds")).toBeVisible();
  await expect(page.getByRole("status")).toContainText(
    "No ticket or run was created",
  );
  const manualIdea = page
    .locator(".idea-list article")
    .filter({ hasText: "Clarify shipping thresholds" });
  await manualIdea.getByRole("button", { name: "Archive" }).click();
  await expect(
    manualIdea.getByRole("button", { name: "Restore" }),
  ).toBeVisible();
  await manualIdea.getByRole("button", { name: "Restore" }).click();
  await manualIdea.getByRole("button", { name: "Draft ticket" }).click();
  await expect(page.getByRole("tab", { name: /Tickets/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue(
    "Clarify shipping thresholds",
  );

  await page.getByRole("tab", { name: /Projects/ }).click();
  await page.getByRole("tab", { name: /Organizations/ }).click();
  await page.getByLabel("Selected project organization").fill("Checkout Labs");
  await page.getByRole("button", { name: "Save organization" }).click();
  await expect(page.locator(".organization-list h3")).toHaveText(
    "Checkout Labs",
  );
  await expect(page.getByRole("status")).toContainText("grants no authority");
});

test("interruption and terminal failure state what happened and how to continue", async ({
  page,
}) => {
  const interrupted = base([project, ticket, plan]);
  (interrupted.workspace.durable_activities as unknown[]) = [
    {
      id: "D1",
      ticket_id: "T1",
      activity_kind: "IMPLEMENTATION_SANDBOX",
      status: "INTERRUPTED",
      stage: "IMPLEMENTATION",
      resumable: true,
      error: "Worker process stopped.",
      updated_at: "2026-08-16T12:00:00Z",
    },
  ];
  const ctl = await mockApi(page, interrupted);
  await page.goto("/");
  await page.getByRole("tab", { name: /Runs/ }).click();
  await expect(page.getByLabel("Active work context")).toContainText(
    "Recovery needed",
  );
  await page.getByRole("tab", { name: /Runs/ }).click();
  await page.getByRole("button", { name: "Resume run" }).click();
  await expect(page.getByRole("status")).toContainText(
    "same limits and authority",
  );
  ctl.set(
    base([
      project,
      ticket,
      plan,
      {
        ...attempt,
        status: "FAILED",
        failure_reason: "Validation command exited unsuccessfully",
        original_unchanged: true,
      },
    ]),
  );
  await page.reload();
  await page.getByRole("tab", { name: /Tickets/ }).click();
  await page.getByRole("button", { name: /Plan and implementation/ }).click();
  const next = page.getByRole("region", { name: "Next ticket step" });
  await expect(next).toContainText("Implementation failed · task still open");
  await expect(next).toContainText("Validation command exited unsuccessfully");
  await next.getByRole("button", { name: "Read failure details" }).click();
  await expect(next.getByRole("button", { name: "Request replacement plan" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve and apply change" })).toHaveCount(0);
});

test("a blocking action error explains the failure without advancing authority", async ({
  page,
}) => {
  await mockApi(page, base([project, ticket, plan]));
  await page.route("http://127.0.0.1:8787/api/tickets/approve-plan", (route) =>
    route.fulfill({
      status: 409,
      json: { error: "Plan approval is blocked because its source changed." },
    }),
  );
  await page.goto("/");
  await page.getByRole("tab", { name: /Tickets/ }).click();
  await page.getByRole("button", { name: /Plan and implementation/ }).click();
  await page.getByRole("button", { name: "Read proposed plan" }).click();
  await page.locator(".ticket-next-step")
    .getByRole("button", { name: "Approve plan", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Plan approval is blocked because its source changed",
  );
  await expect(page.getByRole("button", { name: "Start implementation in isolated copy" })).toHaveCount(0);
});

test("loading and retryable service errors are announced", async ({ page }) => {
  let calls = 0;
  await page.route("http://127.0.0.1:8787/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/profiles") return route.fulfill({ json: { profiles: [testProfile] } });
    if (path === "/api/profiles/me") return route.fulfill({ json: { profile: testProfile } });
    if (path === "/api/models") return route.fulfill({ json: modelSettings });
    if (path === "/api/snapshot") {
      calls++;
      if (calls === 1) {
        await new Promise((r) => setTimeout(r, 250));
        return route.fulfill({ status: 503, json: { error: "offline" } });
      }
      return route.fulfill({ json: base() });
    }
    if (path === "/api/workspace/options")
      return route.fulfill({ json: { projects: [], limits: {} } });
    return route.fulfill({ json: { tests: [], limits: {} } });
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Opening Observer" }),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toContainText(
    "Observer service is unavailable",
  );
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("tab", { name: /Overview/ })).toBeVisible();
});

test("narrow viewport preserves direct navigation, context, and visible focus", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 740 });
  await mockApi(page, base([project, ticket, plan, attempt]));
  await page.goto("/");
  const ticketsTab = page.getByRole("tab", { name: /Tickets/ });
  await ticketsTab.focus();
  await expect(ticketsTab).toBeFocused();
  await expect(ticketsTab).toBeInViewport();
  await ticketsTab.press("Enter");
  await expect(page.getByLabel("Active work context")).toBeVisible();
  await expect(page.getByText("CURRENT STATE").first()).toBeVisible();
});

test("run result moves coherently to exact files and validation detail", async ({
  page,
}) => {
  await mockApi(page, base([project, ticket, plan, attempt]));
  await page.goto("/");
  await page.getByRole("tab", { name: /Tickets/ }).click();
  await page.getByRole("button", { name: /Plan and implementation/ }).click();
  await page
    .getByText("Review files, validation, and recorded authority →")
    .click();
  await expect(page.getByRole("tab", { name: /Inspect/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  const inspect = page.getByRole("complementary").filter({ has: page.getByRole("heading", { name: "Validated proposal" }) });
  await expect(inspect.getByText("checkout/pricing.py").first()).toBeVisible();
  await expect(inspect.getByText(/PASSED · pytest -q/).first()).toBeVisible();
});
