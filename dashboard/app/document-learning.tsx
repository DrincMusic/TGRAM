"use client";

import { useState } from "react";

type Receipt = {
  document_id: string; title: string; source_ref: string; saved_count: number; reused: boolean;
  collection_names: string[]; review_scope: string;
  decisions: Array<{ candidate: number; statement: string; excerpt: string; outcome: string; reason: string; collection?: string; lesson_id?: string }>;
};

export function DocumentLearningPanel({ api, token, projectId, onSaved }: {
  api: string; token: string; projectId: string; onSaved: () => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

  async function loadHistory() {
    const response = await fetch(`${api}/api/learning/documents?project_id=${encodeURIComponent(projectId)}`, { headers });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Document history could not be loaded.");
    setReceipts(result.documents);
  }
  async function run(work: () => Promise<void>) {
    setBusy(true); setMessage("");
    try { await work(); } catch (error) { setMessage(error instanceof Error ? error.message : "Document learning failed."); }
    finally { setBusy(false); }
  }
  return <details>
    <summary>Learn from a document</summary>
    <p>Paste document text or open a UTF-8 text/Markdown file. TGRAM extracts up to 12 candidates, checks their source support, and saves supported facts into project knowledge collections. Existing collections are reused when suitable. Conflicts remain unsaved for review.</p>
    <form onSubmit={event => { event.preventDefault(); void run(async () => {
      setMessage("Extracting candidates, then reviewing their source support. This can take up to two minutes.");
      const response = await fetch(`${api}/api/learning/documents`, { method: "POST", headers,
        body: JSON.stringify({ project_id: projectId, document: { title, source_ref: source, text } }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The document could not be learned.");
      await loadHistory(); await onSaved();
      setMessage(result.document.reused ? "This document was already reviewed; its saved report is shown below."
        : `Review complete. ${result.document.saved_count} facts saved and indexed for conversation and project work.`);
    }); }}>
      <label>Open a text document<input type="file" accept=".txt,.md,text/plain,text/markdown" disabled={busy} onChange={event => {
        const file = event.target.files?.[0]; if (!file) return;
        void run(async () => {
          if (file.size > 96000) throw new Error("Choose a smaller document section: the limit is 24,000 characters / 96 KB.");
          const contents = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
          if (contents.length > 24000 || contents.includes("\0")) throw new Error("Use readable text with at most 24,000 characters.");
          setText(contents); setTitle(file.name); setSource(file.name);
        });
      }} /></label>
      <label>Document title<input required maxLength={160} value={title} onChange={e => setTitle(e.target.value)} disabled={busy} /></label>
      <label>Source URL or document reference<input required maxLength={500} value={source} onChange={e => setSource(e.target.value)} disabled={busy} /></label>
      <label>Document text<textarea required rows={8} maxLength={24000} value={text} onChange={e => setText(e.target.value)} disabled={busy} /></label>
      <small>{text.length.toLocaleString()} / 24,000 characters. URLs are recorded as references; they are not fetched. Use one coherent section of a longer work.</small>
      <button type="submit" disabled={busy || !projectId}>{busy ? "Working…" : "Read, review, and save supported facts"}</button>
    </form>
    <button type="button" disabled={busy} onClick={() => void run(loadHistory)}>Load document review history</button>
    {message && <p role="status">{message}</p>}
    {receipts.slice(0, 12).map(receipt => <details key={receipt.document_id} className="memory-card">
      <summary>{receipt.title} · {receipt.saved_count} facts saved</summary>
      <p>Source: {receipt.source_ref}</p><p>{receipt.review_scope}</p>
      <p>Collections: {receipt.collection_names.join(", ") || "No facts saved"}</p>
      {!receipt.decisions.length && <p>No usable fact candidates were extracted.</p>}
      {receipt.decisions.map(decision => <article className="memory-card" key={decision.candidate}>
        <b>{decision.outcome}</b><p>{decision.statement}</p><p>{decision.reason}</p>
        <details><summary>Supporting excerpt</summary><blockquote>{decision.excerpt}</blockquote></details>
        {decision.collection && <small>Saved in {decision.collection}</small>}
      </article>)}
    </details>)}
  </details>;
}
