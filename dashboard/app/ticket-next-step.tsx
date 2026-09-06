"use client";

import { useState } from "react";
import { FileChangePreview } from "./file-change-preview";

type Plan = { id: string; answer?: string; prompt?: string; affected_paths?: string[]; approval_status?: string };
type Attempt = { id: string; status: string; failure_reason?: string | null };
export function ticketStep(status: string, plan?: Plan, attempt?: Attempt, running = false, closureReady = false) {
  if (running) return "running";
  if (status === "CLOSED") return "closed";
  if (status === "SATISFIED") return "close";
  if (closureReady) return "finish";
  if (!plan) return "plan";
  if (plan.approval_status === "DENIED") return "rejected";
  if (attempt?.status === "FAILED") return "failed";
  if (attempt) return "result";
  return plan.approval_status === "APPROVED" ? "implement" : "review";
}

export function TicketNextStep({ status, plan, attempt, running, busy, closureReady, onPlan, onDecision, onImplement, onResult, onFinish, onClose }: {
  status: string; plan?: Plan; attempt?: Attempt; running: boolean; busy: boolean; closureReady?: boolean;
  onPlan: () => void; onDecision: (decision: string, reason: string) => Promise<boolean>;
  onImplement: () => void; onResult: () => void; onFinish: () => void; onClose: () => void;
}) {
  const [reviewedPlan, setReviewedPlan] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [readAttempt, setReadAttempt] = useState<string | null>(null);
  const step = ticketStep(status, plan, attempt, running, closureReady);
  const copy = {
    running: ["Work in progress", "Wait for this step to finish. No approval or start action is needed."],
    closed: ["Ticket closed", "This task is complete. Its plan, results and decisions remain in the history below."],
    close: ["Ready to close", "The task has been marked satisfied. Close it to finish the workflow."],
    finish: ["Completion checks resolved", "Review the recorded acceptance evidence below, then mark the task satisfied."],
    plan: ["Step 1 · Create a plan", "Planning proposes changes. It does not implement or apply them."],
    rejected: ["Plan rejected · task still open", "The rejected plan will not run. Request a replacement when you are ready to continue."],
    failed: ["Implementation failed · task still open", attempt?.failure_reason || "The last attempt failed. Review its result before deciding how to continue."],
    result: ["Review the implementation result", "Inspect the changed files and validation results before authorizing any application to your project."],
    implement: ["Step 3 · Start implementation", "The plan is approved. This next step works in an isolated copy; it does not apply changes to your project."],
    review: ["Step 2 · Review the plan", "Read the proposed changes and authorized files before deciding whether to approve them."],
  }[step];
  return <section className="ticket-next-step" aria-label="Next ticket step" aria-live="polite">
    <h3>{copy[0]}</h3><p>{copy[1]}</p>
    {["plan", "rejected"].includes(step) && <button className="primary" disabled={busy} onClick={onPlan}>{step === "rejected" ? "Request replacement plan" : "Create plan"}</button>}
    {step === "review" && plan && (reviewedPlan !== plan.id ?
      <button className="primary" disabled={busy} onClick={() => setReviewedPlan(plan.id)}>Read proposed plan</button> :
      <div className="ticket-plan-review">
        <h4>Proposed changes</h4>
        <p className="ticket-plan-text">{plan.answer || "No plan summary was supplied. Reject this plan and request a readable replacement."}</p>
        <h4>Files this plan permits changing</h4>
        <div>{plan.affected_paths?.map((path) => <FileChangePreview key={path} path={path} context={plan.answer} />)}</div>
        {rejecting ? <form onSubmit={async (event) => {
          event.preventDefault();
          if (await onDecision("DENIED", reason.trim())) { setRejecting(false); setReason(""); }
        }}>
          <label>Why should the plan change?<textarea required maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
          <button disabled={busy || !reason.trim()}>Record rejection</button>
          <button type="button" disabled={busy} onClick={() => setRejecting(false)}>Back to plan</button>
        </form> : <div className="button-row">
          <button className="primary" disabled={busy || !plan.answer || !plan.affected_paths?.length} onClick={() => void onDecision("APPROVED", "User reviewed the displayed plan and authorized implementation. Implementation has not been started by this decision.")}>Approve plan</button>
          <button disabled={busy} onClick={() => setRejecting(true)}>Reject plan</button>
        </div>}
        <small>Approval records your decision. Starting implementation is the next separate step.</small>
      </div>)}
    {step === "implement" && <button className="primary" disabled={busy} onClick={onImplement}>Start implementation in isolated copy</button>}
    {step === "failed" && readAttempt === attempt?.id ?
      <button className="primary" disabled={busy} onClick={onPlan}>Request replacement plan</button> :
      ["failed", "result"].includes(step) && <button className="primary" disabled={busy} onClick={() => { setReadAttempt(attempt!.id); onResult(); }}>{step === "failed" ? "Read failure details" : "Review changes and validation"}</button>}
    {step === "finish" && <button className="primary" disabled={busy} onClick={onFinish}>Mark task satisfied</button>}
    {step === "close" && <button className="primary" disabled={busy} onClick={onClose}>Close ticket</button>}
  </section>;
}
