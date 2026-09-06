"use client";

import { useState } from "react";

export type MemoryFact = {
  id: string; session_id: string; subject: string; predicate: string; value: string;
  source_turn_id: string; supersedes_fact_id?: string | null; created_at: string;
  meaning?: string; source_excerpt?: string; useful_when?: string; confidence?: number;
  supporting_turn_ids?: string[]; last_confirmed_at?: string | null;
};
export type MemoryReceipt = {
  fact_ids: string[]; cited_fact_ids: string[]; turn_ids: string[]; token_estimate: number;
};
export async function shareConversationFact(api: string, token: string, projectId: string, fact: MemoryFact) {
  const response = await fetch(`${api}/api/world-memory/link`, {
    method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ project_id: projectId, session_id: fact.session_id, fact_id: fact.id }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Fact could not be linked.");
}
export type SavedConversation = {
  id: string; title: string; updated_at: string;
  conversation_facts?: MemoryFact[];
  turns: Array<{
    id: string; user_message: string; answer: string;
    superseded_by_turn_id?: string | null;
    ticket_id?: string; project_id?: string;
    route?: string; claim_confidence?: number; routing_confidence?: number;
    routing_reason?: string; reuse_kind?: string; scope?: string;
    task_id?: string; claim_id?: string; evidence?: Array<Record<string, unknown>>;
    task_tree?: Array<{ id: string; question: string; depth: number; status: string }>;
    investigation_mode?: string; context_claim_ids?: string[];
    context_token_estimate?: number; work_project_id?: string;
    conversation_memory_receipt?: MemoryReceipt | null;
  }>;
};

function catalog(sessions: SavedConversation[]) {
  const superseded = new Set(sessions.flatMap((session) => session.turns)
    .filter((turn) => turn.superseded_by_turn_id).map((turn) => turn.id));
  return sessions.flatMap((session) => session.conversation_facts || [])
    .filter((fact) => !superseded.has(fact.source_turn_id));
}

function MemoryCard({ fact, sessions, cited, onCorrect, onShare }: {
  fact: MemoryFact; sessions: SavedConversation[]; cited?: boolean;
  onCorrect?: (fact: MemoryFact) => void;
  onShare?: (fact: MemoryFact) => Promise<void>;
}) {
  const [shareStatus, setShareStatus] = useState("");
  const [sharing, setSharing] = useState(false);
  const replacement = catalog(sessions).find((item) => item.supersedes_fact_id === fact.id);
  const source = sessions.flatMap((session) => session.turns)
    .find((turn) => turn.id === fact.source_turn_id);
  return <article className="memory-card">
    <div className="memory-card-heading">
      <b>{fact.subject.replaceAll("conversation.", "").replaceAll("user.", "").replaceAll("_", " ")}</b>
      <span>{replacement ? "Superseded" : cited ? "Cited by responder" : "Recorded context"}</span>
    </div>
    <p>{fact.value}</p>
    <small>{fact.predicate} · {new Date(fact.created_at).toLocaleDateString()}</small>
    <details>
      <summary>Source and history</summary>
      <p>{fact.meaning === "REQUIREMENT" ? "User requirement: desired behavior, not proof it has been implemented."
        : fact.meaning === "CONVENTION" ? "Conversation convention: an agreed meaning to use in dialogue."
        : fact.meaning === "PREFERENCE" ? "User preference: guidance for future responses and work."
        : "Reported information: saved from conversation, not independently verified."}</p>
      {fact.useful_when && <p>Useful when: {fact.useful_when}</p>}
      {fact.source_excerpt && <p>Supporting excerpt: <q>{fact.source_excerpt}</q></p>}
      {fact.confidence != null && <p>Extraction confidence: {Math.round(fact.confidence * 100)}%. This measures certainty about the interpretation, not whether the statement is true.</p>}
      {!!fact.supporting_turn_ids?.length && <p>Repeated in {fact.supporting_turn_ids.length} retained conversation reference(s). Repetition does not independently verify a fact.</p>}
      {fact.last_confirmed_at && <small>Last repeated: {new Date(fact.last_confirmed_at).toLocaleDateString()}</small>}
      {source ? <blockquote>{source.user_message}</blockquote> : <p>Source conversation is unavailable.</p>}
      {fact.supersedes_fact_id && <p>Replaces an earlier memory.</p>}
      {replacement && <p>Later correction: {replacement.value}</p>}
      <small>Memory reference: {fact.id}</small>
    </details>
    {onCorrect && !replacement && <button type="button" onClick={() => onCorrect(fact)}>Discuss a correction</button>}
    {onShare && !replacement && <details><summary>Use this fact in project work</summary>
      <p>Share this fact with the selected project&apos;s world memory. It becomes available to project conversations and workers, including other profiles using that project. The original conversation stays private.</p>
      <button type="button" disabled={sharing} onClick={async () => {
        setSharing(true); setShareStatus("");
        try { await onShare(fact); setShareStatus("Linked to the selected project for conversation and work."); }
        catch (error) { setShareStatus(error instanceof Error ? error.message : "Sharing failed."); }
        finally { setSharing(false); }
      }}>{sharing ? "Sharing…" : "Share with selected project"}</button>
      {shareStatus && <p role="status">{shareStatus}</p>}
    </details>}
  </article>;
}

export function ResponseMemory({ receipt, sessions }: {
  receipt?: MemoryReceipt | null; sessions: SavedConversation[];
}) {
  const facts = catalog(sessions);
  return <details className="response-memory">
    <summary>Memory behind this response{receipt ? ` · ${receipt.fact_ids.length} fact${receipt.fact_ids.length === 1 ? "" : "s"}` : ""}</summary>
    {!receipt ? <p>No memory receipt was recorded for this response. This does not establish that no memory was used.</p> : <>
      <p>These facts were supplied to conversation processing. “Cited by responder” means the response stage reported using that fact; it is not independent verification.</p>
      <small>{receipt.turn_ids.length} prior turn reference(s) · approximately {receipt.token_estimate} context tokens</small>
      {!receipt.fact_ids.length && <p>No stored facts were selected. Recent dialogue may still have supplied context.</p>}
      {receipt.fact_ids.map((id) => {
        const fact = facts.find((item) => item.id === id);
        return fact ? <MemoryCard key={id} fact={fact} sessions={sessions} cited={receipt.cited_fact_ids.includes(id)} />
          : <p key={id}>Memory {id} is unavailable in the loaded history.</p>;
      })}
    </>}
  </details>;
}

export function ConversationMemory({ sessions, sessionId, busy, error, onSelect, onRefresh, onCorrect, onShare }: {
  sessions: SavedConversation[]; sessionId: string | null; busy: boolean; error: string;
  onSelect: (id: string) => void; onRefresh: () => void; onCorrect: (fact: MemoryFact) => void;
  onShare?: (fact: MemoryFact) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const facts = catalog(sessions);
  const superseded = new Set(facts.map((fact) => fact.supersedes_fact_id).filter(Boolean));
  const selected = facts.filter((fact) => (showHistory || !superseded.has(fact.id))
    && `${fact.subject} ${fact.predicate} ${fact.value} ${fact.useful_when || ""} ${fact.meaning || ""}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="conversation-library">
    <label>Conversation
      <select aria-label="Saved conversation" value={sessionId || ""} disabled={busy}
        onChange={(event) => onSelect(event.target.value)}>
        <option value="">New conversation</option>
        {sessions.map((session) => <option key={session.id} value={session.id}>{session.title}</option>)}
      </select>
    </label>
    <details className="memory-library">
      <summary>Explore conversation memory · {facts.filter((fact) => !superseded.has(fact.id)).length} current</summary>
      <p>Inspect recorded conversation facts and their original messages. Project evidence remains attached to investigation responses.</p>
      <label>Search memories<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a decision, objective, or preference" /></label>
      <label className="memory-history-toggle"><input type="checkbox" checked={showHistory} onChange={(event) => setShowHistory(event.target.checked)} /> Include superseded memories</label>
      <button type="button" disabled={busy} onClick={onRefresh}>Refresh memory</button>
      {error && <p role="alert">{error}</p>}
      <div className="memory-results">
        {selected.slice(0, 100).map((fact) => <MemoryCard key={fact.id} fact={fact} sessions={sessions} onCorrect={busy ? undefined : onCorrect} onShare={busy ? undefined : onShare} />)}
        {!selected.length && <p>{facts.length ? "No memories match this search." : "No conversation facts have been recorded yet. Start with your objective or a preference you want remembered."}</p>}
        {selected.length > 100 && <p>Showing 100 of {selected.length} matches. Narrow your search to find more.</p>}
      </div>
      <small>Discussing a correction opens a draft message. After sending, check the recorded memory to confirm the update.</small>
    </details>
  </div>;
}
