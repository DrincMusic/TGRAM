"use client";

import { useId, useState } from "react";

export type PreviewChange = { path: string; unified_diff?: string; change_reason?: string | null };

export function FileChangePreview({ path, change, context }: { path: string; change?: PreviewChange; context?: string }) {
  const id = useId();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [pinned, setPinned] = useState(false);
  const open = hovered || focused || pinned;
  return <div className="file-change-preview" onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
    onFocus={() => setFocused(true)} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false); }}>
    <button type="button" className="file-preview-trigger" aria-expanded={open} aria-controls={id} onClick={() => setPinned(!pinned)}
      onKeyDown={(event) => { if (event.key === "Escape") { setHovered(false); setFocused(false); setPinned(false); } }}>
      <span>{path}</span><small>{change?.unified_diff ? "View changes" : "Proposal only"}</small>
    </button>
    <div id={id} hidden={!open} className="file-preview-content" role="region" aria-label={`Change preview for ${path}`}>
      <p><b>Why this file changes</b></p>
      <p>{change?.change_reason || "No file-specific reason was recorded. Ask for justification before approving changes you do not understand."}</p>
      {context && !change?.change_reason && <details><summary>Overall plan context — not a file-specific justification</summary><p>{context}</p></details>}
      {change?.unified_diff ? <>
        <p><b>Captured changes</b> · − removed · + added</p>
        <div className="file-preview-diff" tabIndex={0} role="textbox" aria-readonly="true" aria-multiline="true" aria-label={`Diff for ${path}`}
          onKeyDown={(event) => { if (event.key === "Escape") { setHovered(false); setFocused(false); setPinned(false); } }}><code>{change.unified_diff.split("\n").map((line, index) =>
          <span key={index} className={line.startsWith("+") && !line.startsWith("+++") ? "diff-added" : line.startsWith("-") && !line.startsWith("---") ? "diff-removed" : ""}>{line}{"\n"}</span>
        )}</code></div>
      </> : <p>No captured diff exists for this file. Being authorized in a plan does not mean it has been changed.</p>}
      <small>{pinned ? "Preview pinned. Click the file again to unpin, or press Escape to close." : "Click the file to keep this preview open. Escape closes it."}</small>
    </div>
  </div>;
}
