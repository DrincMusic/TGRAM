import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Compile only this component in memory; no browser traces or fixture files.
const source = await readFile(new URL("../app/conversation-memory.tsx", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
});
const compiledModule = { exports: {} };
new Function("require", "module", "exports", outputText)(createRequire(import.meta.url), compiledModule, compiledModule.exports);
const { ConversationMemory, ResponseMemory } = compiledModule.exports;
const facts = [
  { id: "old", session_id: "s1", subject: "conversation.current_project", predicate: "is", value: "Alpha", source_turn_id: "t1", created_at: "2026-09-04T10:00:00Z" },
  { id: "new", session_id: "s1", subject: "conversation.current_project", predicate: "is", value: "TGRAM", source_turn_id: "t2", supersedes_fact_id: "old", created_at: "2026-09-04T11:00:00Z" },
];
const sessions = [{ id: "s1", title: "Our project", conversation_facts: facts, turns: [
  { id: "t1", user_message: "This project is Alpha", answer: "Recorded" },
  { id: "t2", user_message: "This project is TGRAM", answer: "Updated" },
] }];
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props));

test("retried exchanges do not keep derived facts in current memory", () => {
  const replaced = [{ ...sessions[0], turns: sessions[0].turns.map((turn) =>
    turn.id === "t1" ? { ...turn, superseded_by_turn_id: "t2" } : turn) }];
  const html = render(ResponseMemory, {
    receipt: { fact_ids: ["old", "new"], cited_fact_ids: [], turn_ids: ["t2"], token_estimate: 30 },
    sessions: replaced,
  });
  assert.ok(!html.includes("Alpha"));
  assert.ok(html.includes("TGRAM"));
});

test("historical receipt shows original source and later correction without rewriting history", () => {
  const html = render(ResponseMemory, { sessions, receipt: { fact_ids: ["old"], cited_fact_ids: ["old"], turn_ids: ["t1"], token_estimate: 42 } });
  assert.match(html, /This project is Alpha/);
  assert.match(html, /Later correction: TGRAM/);
  assert.match(html, /Superseded/);
  assert.match(html, /42 context tokens/);
});

test("missing receipts and inaccessible sources are explicit rather than invented", () => {
  assert.match(render(ResponseMemory, { sessions }), /No memory receipt was recorded/);
  assert.match(render(ResponseMemory, { sessions: [], receipt: { fact_ids: ["foreign"], cited_fact_ids: [], turn_ids: [], token_estimate: 0 } }), /unavailable in the loaded history/);
});

test("library offers conversation selection and hides superseded facts by default", () => {
  const html = render(ConversationMemory, { sessions, sessionId: "s1", busy: false, error: "", onSelect() {}, onRefresh() {}, onCorrect() {} });
  assert.match(html, /Saved conversation/);
  assert.match(html, /Our project/);
  assert.match(html, /Discuss a correction/);
  assert.doesNotMatch(html, /This project is Alpha/);
  assert.match(html, /This project is TGRAM/);
});
