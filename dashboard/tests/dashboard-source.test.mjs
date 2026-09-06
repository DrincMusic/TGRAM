import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const mainPage = await readFile(
  new URL("../app/page.tsx", import.meta.url),
  "utf8",
);

const page = mainPage + await readFile(new URL("../app/ticket-next-step.tsx", import.meta.url), "utf8");

test("Observer opens as a coherent durable workspace", () => {
  assert.match(page, /\/api\/snapshot/);
  assert.match(page, /setInterval\(refresh, 2000\)/);
  assert.match(page, /next\.workspace\?\.focus_ticket_id/);
  assert.match(page, /Work requiring a decision\./);
  assert.match(page, /Active work context/);
  assert.match(page, /aria-label="Active run"/);
  assert.match(page, /aria-label="Account and personalization"/);
  assert.match(page, /tgram-profile-session/);
  assert.match(page, /Create profile/);
  assert.match(page, /No cloud account required/);
  assert.doesNotMatch(page, /hidden=\{activeTab !== "work"\}\s+className="active-task"/);
  assert.match(page, /CURRENT STATE/);
  assert.match(page, /NEXT AVAILABLE ACTION/);
  assert.match(page, /const overviewTicket = overviewWorkItems\[overviewTicketIndex\]/);
  assert.match(page, /Ticket \{overviewTicketIndex \+ 1\} of \{overviewWorkItems\.length\}/);
  assert.doesNotMatch(page, /snapshot\.workspace\.work_items\.map/);
  assert.match(page, /overview-chat chat-text-/);
  assert.match(page, /tgram-chat-text-/);
  assert.match(page, /Overview/);
  assert.match(page, /Needs attention/);
  assert.match(page, /SELECTED PROJECT/);
  assert.match(page, /SELECTED TICKET/);
  assert.match(page, /<details className="ticket-create ticket-new-task">/);
  assert.equal((mainPage.match(/className="ticket-information-panel"/g) || []).length, 4);
  assert.match(mainPage, /aria-label="Ticket work and next step"/);
  assert.match(mainPage, /aria-label="Active ticket information"/);
  assert.match(mainPage, /setTicketInfo\(\{ ticketId: activeTicket.id, section: "plan" \}\)/);
  assert.match(page, /role="tablist"/);
  assert.match(page, /aria-selected=\{activeTab === tab\.id\}/);
  for (const value of [
    "Projects",
    "Tickets",
    "Runs",
    "Inspect",
    "No recorded blocker",
  ])
    assert.match(page, new RegExp(value));
  assert.doesNotMatch(page, /YOUR JOURNEY|STEP [0-9]|first-use-guide/);
});

test("daily workflow exposes resume, completion, and export actions", () => {
  for (const label of [
    "Tickets",
    "Projects",
    "Runs",
    "Inspect",
    "Resume run",
    "Export audit record",
    "Close ticket",
    "Completion gates resolved",
    "Completion blocked",
    "Choose current evidence",
    "Answer ticket question",
    "Approve and apply change",
    "Recover interrupted apply",
    "Refresh project index",
  ]) {
    assert.match(page, new RegExp(label));
  }
  assert.match(page, /\/api\/tickets\/export\?ticket_id=/);
  assert.match(page, /\/api\/\$\{path\}\/resume/);
  assert.match(page, /setActiveTab\("lab"\)/);
});

test("approval hardening exposes roles, thresholds, history, and expiration", () => {
  for (const value of [
    "Reviewer roles",
    "Approval rules",
    "Artifact validation",
    "Append-only policy history",
    "Who approved or rejected what",
    "Older decisions remain here",
    "Reject plan",
    "Approve and apply change",
    "Reject change",
    "approval_expiration_reasons",
    "promotion_approval_expiration_reasons",
    "policy_version",
    "rule_id",
    "binding_sha256",
  ])
    assert.match(page, new RegExp(value));
  assert.match(page, /actor_roles: JSON\.parse/);
  assert.match(page, /approval_rules: JSON\.parse/);
  assert.match(page, /artifact_validation_requirements: JSON\.parse/);
});

test("resource-aware scheduling exposes queue rationale and safe cancellation", () => {
  for (const value of [
    "RESOURCE-AWARE SCHEDULER",
    "Capacity, budgets, and durable queue decisions",
    /predicted cost, latency, capacity,\s+and validation needs/,
    "Cancel run",
    "WAITING_FOR_CAPACITY",
    "WAITING_FOR_LEASE",
    "blocked_reason",
    "scheduling_reasons",
    "resources_disposed",
    "/cancel",
  ])
    assert.match(page, new RegExp(value));
});

test("demo and graph-proof controls are isolated in the optional technical lab", () => {
  assert.match(page, /OPTIONAL TECHNICAL LAB/);
  assert.match(
    page,
    /These proof surfaces are kept outside the daily ticket workflow/,
  );
  assert.match(page, /Reset demo data/);
  assert.match(page, /Run demonstration/);
  assert.doesNotMatch(page, /ADVANCED TEST DIAGNOSTIC/);
  assert.match(page, /TASK GRAPH/);
  assert.doesNotMatch(page, /SkeletonPreview|codex-preview|JSON\.stringify/);
});

test("multi-project governance is visible and configurable per registered root", () => {
  for (const value of [
    "PROJECT GOVERNANCE",
    "Authorization stays inside this project",
    "Cross-project dependencies are read-only",
    "Configure policy",
    "Project manifest, goals, ideas, and organizations",
    "manifest.md",
    "goals.json",
    "SCAN ",
    "Save idea",
    "Source-grounded candidates",
    "Suggest ideas",
    "Results stay unsaved until you choose one",
    "Save organization",
    "Organization labels grant no identity",
    "Permitted worker IDs",
    "Required validation categories",
    "Plan approver identities",
    "Promotion approver identities",
  ])
    assert.match(page, new RegExp(value));
  assert.match(page, /no ticket, run, or\s+write authority/);
  assert.match(page, /\/api\/projects\/policy/);
  assert.match(page, /selectedGovernancePolicy\.project_root/);
  assert.match(page, /\/api\/projects\/browse/);
  assert.match(page, /Browse for project folder/);
  assert.match(page, /\/api\/projects\/connect/);
  assert.match(page, /path: "organization" \| "access" \| "intent" \| "goals" \| "ideas" \| "ideas\/status"/);
  assert.match(page, /\/api\/projects\/\$\{path\}/);
  assert.match(page, /\/api\/projects\/ideas\/suggest/);
  assert.match(page, /Connect project/);
  assert.match(page, /Managed project/);
  assert.match(page, /onChange=\{\(event\) => chooseWorkspaceProject\(event\.target\.value\)\}/);
  assert.doesNotMatch(page, /ACTIVE PROJECT/);
  assert.match(page, /projectSelectionExplicit\.current = true/);
  assert.match(page, /if \(projectSelectionExplicit\.current\) return ""/);
});

test("savings explains actual, avoided, and estimated token usage", () => {
  for (const value of [
    "Tokens TGRAM used",
    "Estimated use without savings",
    "Tokens avoided",
    "total_token_usage",
    "potential_total_token_usage",
    "unmetered_model_calls",
  ])
    assert.match(page, new RegExp(value));
  for (const value of [
    "What the totals mean",
    "How much of this is directly measured",
    "Show technical token and cache diagnostics",
    "savings-metrics",
    "savings-notice",
  ])
    assert.match(page, new RegExp(value));
});
