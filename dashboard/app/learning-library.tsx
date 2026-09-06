"use client";

import { useState } from "react";
import { DocumentLearningPanel } from "./document-learning";

type Lesson = {
  id: string; topic: string; statement: string; source_ref: string; source_excerpt: string;
  source_kind: string; applies_when: string; limitations: string; status: string;
  outcome_counts?: Record<string, number>;
  collection_name?: string;
  reports: Array<{ outcome: string; context: string; observation: string; evidence_ref: string }>;
};

export function LearningLibrary({ api, token, projectId }: { api: string; token: string; projectId: string }) {
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

  async function refresh() {
    const response = await fetch(`${api}/api/lessons?project_id=${encodeURIComponent(projectId)}`, { headers });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Lessons could not be loaded.");
    setLessons(result.lessons);
  }
  async function act(work: () => Promise<void>) {
    setBusy(true); setMessage("");
    try { await work(); } catch (error) { setMessage(error instanceof Error ? error.message : "Request failed."); }
    finally { setBusy(false); }
  }
  async function save(form: HTMLFormElement, lessonId?: string) {
    const values = Object.fromEntries(new FormData(form).entries());
    const response = await fetch(`${api}/api/lessons${lessonId ? "/report" : ""}`, {
      method: "POST", headers, body: JSON.stringify({ project_id: projectId,
        ...(lessonId ? { lesson_id: lessonId, report: values } : { lesson: values }) }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Lesson could not be saved.");
    form.reset(); await refresh(); setMessage(lessonId ? "Application report saved." : "Lesson saved for this project.");
  }
  const input = (name: string, label: string, maxLength: number) => <label>{label}
    <textarea name={name} required maxLength={maxLength} rows={2} style={{ width: "100%" }} /></label>;
  return <details className="memory-library">
    <summary>Learning · sourced lessons and experience</summary>
    <p>Teach TGRAM a lesson from reading, a GPT explanation, or experience. Lessons are shared within the selected project and retrieved during conversation and investigation. Sources are recorded as supplied; saving does not verify them or run an experiment.</p>
    {!projectId ? <p>Select a connected project to begin.</p> : <>
      <button type="button" disabled={busy} onClick={() => void act(refresh)}>Load / refresh lessons</button>
      <DocumentLearningPanel api={api} token={token} projectId={projectId} onSaved={refresh} />
      <details><summary>Teach a lesson</summary>
        <form onSubmit={event => { event.preventDefault(); const form = event.currentTarget; void act(() => save(form)); }}>
          {input("topic", "Topic", 160)}
          {input("statement", "What should TGRAM learn?", 2000)}
          <label>Source type<select name="source_kind"><option value="PUBLICATION">Publication or documentation</option><option value="GPT_EXPLANATION">GPT explanation</option><option value="EXPERIENCE">Experience</option></select></label>
          {input("source_ref", "Source URL, conversation reference, or experiment reference", 500)}
          {input("source_excerpt", "Supporting excerpt or observation", 1000)}
          {input("applies_when", "When is this useful?", 600)}
          {input("limitations", "Assumptions, limitations, or what remains unknown", 600)}
          <button type="submit" disabled={busy}>Save lesson for this project</button>
        </form>
      </details>
      <label>Find a lesson<input value={query} onChange={event => setQuery(event.target.value)} /></label>
      {lessons.filter(lesson => `${lesson.topic} ${lesson.statement} ${lesson.collection_name || ""}`.toLowerCase().includes(query.toLowerCase())).slice(0, 20).map(lesson =>
        <details className="memory-card" key={lesson.id}><summary>{lesson.topic} · {lesson.status.replaceAll("_", " ").toLowerCase()}</summary>
          <p>{lesson.statement}</p><p>Useful when: {lesson.applies_when}</p><p>Limits: {lesson.limitations}</p>
          {lesson.collection_name && <small>Collection: {lesson.collection_name}</small>}
          <p>Source ({lesson.source_kind.replaceAll("_", " ")}): {lesson.source_ref}</p><blockquote>{lesson.source_excerpt}</blockquote>
          <p>Application reports describe specific experiences. They do not establish universal truth. The latest 12 are retained.</p>
          <p>Reported outcomes: {lesson.outcome_counts?.HELPED || 0} helped, {lesson.outcome_counts?.DID_NOT_HELP || 0} did not help, {lesson.outcome_counts?.INCONCLUSIVE || 0} inconclusive. Negative reports keep the lesson marked contested even after older detailed notes expire.</p>
          {lesson.reports.map((report, index) => <p key={index}>{report.outcome}: {report.context} — {report.observation} (Evidence: {report.evidence_ref})</p>)}
          <details><summary>Record what happened when applied</summary><form onSubmit={event => { event.preventDefault(); const form = event.currentTarget; void act(() => save(form, lesson.id)); }}>
            <label>Outcome<select name="outcome"><option value="INCONCLUSIVE">Inconclusive</option><option value="HELPED">Helped in this case</option><option value="DID_NOT_HELP">Did not help in this case</option></select></label>
            {input("context", "Where and how was it applied?", 600)}{input("observation", "What happened? Include measurements if available.", 1000)}{input("evidence_ref", "Test, run, or observation reference", 500)}
            <button type="submit" disabled={busy}>Save application report</button>
          </form></details>
        </details>)}
      <small>Showing up to 20 matching lessons. Narrow the search for more.</small>
    </>}
    {message && <p role="status">{message}</p>}
  </details>;
}
