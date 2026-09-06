import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const source = await readFile(new URL("../app/ticket-next-step.tsx", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
});
const compiledModule = { exports: {} };
const previewSource = await readFile(new URL("../app/file-change-preview.tsx", import.meta.url), "utf8");
const previewModule = { exports: {} };
new Function("require", "module", "exports", ts.transpileModule(previewSource, {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
}).outputText)(createRequire(import.meta.url), previewModule, previewModule.exports);
new Function("require", "module", "exports", outputText)((id) => id === "./file-change-preview" ? previewModule.exports : createRequire(import.meta.url)(id), compiledModule, compiledModule.exports);
const { ticketStep, TicketNextStep } = compiledModule.exports;
const plan = { id: "p1", approval_status: "PENDING", answer: "Improve the chat composer", affected_paths: ["dashboard/app/page.tsx"] };

test("file previews show recorded diff and reason without inventing proposal changes", () => {
  const render = (props) => renderToStaticMarkup(React.createElement(previewModule.exports.FileChangePreview, props));
  const actual = render({ path: "service.py", change: { path: "service.py", unified_diff: "-old\n+new", change_reason: "Correct the requested calculation" } });
  assert.match(actual, /Correct the requested calculation/);
  assert.match(actual, /diff-added/);
  assert.match(actual, /diff-removed/);
  assert.match(actual, /aria-expanded="false"/);
  const proposed = render({ path: "service.py", context: "Overall proposal" });
  assert.match(proposed, /No captured diff exists/);
  assert.match(proposed, /No file-specific reason was recorded/);
  assert.match(proposed, /not a file-specific justification/);
});

test("ticket workflow chooses one stage and rejects stale approval controls", () => {
  assert.equal(ticketStep("ACTIVE"), "plan");
  assert.equal(ticketStep("ACTIVE", plan), "review");
  assert.equal(ticketStep("ACTIVE", { ...plan, approval_status: "DENIED" }, { id: "a", status: "FAILED" }), "rejected");
  assert.equal(ticketStep("ACTIVE", { ...plan, approval_status: "APPROVED" }), "implement");
  assert.equal(ticketStep("ACTIVE", plan, { id: "a", status: "FAILED" }), "failed");
  assert.equal(ticketStep("ACTIVE", plan, { id: "a", status: "READY_FOR_REVIEW" }), "result");
  assert.equal(ticketStep("ACTIVE", plan, undefined, true), "running");
  assert.equal(ticketStep("ACTIVE", plan, undefined, false, true), "finish");
  assert.equal(ticketStep("SATISFIED", plan), "close");
  assert.equal(ticketStep("CLOSED", plan), "closed");
});

test("denied plan explains open task and offers only replacement planning", () => {
  const html = renderToStaticMarkup(React.createElement(TicketNextStep, {
    status: "ACTIVE", plan: { ...plan, approval_status: "DENIED" }, running: false, busy: false,
  }));
  assert.match(html, /task still open/);
  assert.match(html, /Request replacement plan/);
  assert.doesNotMatch(html, /Approve plan|Start implementation/);
  assert.equal((html.match(/<button/g) || []).length, 1);
});

test("pending plan requires reading before displaying approval", () => {
  const html = renderToStaticMarkup(React.createElement(TicketNextStep, { status: "ACTIVE", plan, running: false, busy: false }));
  assert.match(html, /Read proposed plan/);
  assert.doesNotMatch(html, />Approve plan</);
  assert.equal((html.match(/<button/g) || []).length, 1);
});

test("running work exposes no duplicate start or approval action", () => {
  const html = renderToStaticMarkup(React.createElement(TicketNextStep, { status: "ACTIVE", plan, running: true, busy: false }));
  assert.match(html, /Work in progress/);
  assert.doesNotMatch(html, /<button/);
});
