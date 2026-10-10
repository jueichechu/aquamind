"use client";

import { useRef, useState } from "react";

type Proposal = {
  approval_id: string;
  status: "approval_required" | "approved" | "rejected" | "expired" | "conflict";
  arguments: { daily_gallons: number };
  summary: string;
};
const button = "rounded-lg border border-cyan-300/30 px-4 py-2 text-sm text-cyan-100 hover:bg-cyan-300/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:opacity-50";

export function GoalApproval() {
  const token = useRef<string | null>(null);
  const [gallons, setGallons] = useState("150");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [goal, setGoal] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function call(path: string, body?: object) {
    const response = await fetch(`/api/aquamind/v1/${path}`, {
      method: body ? "POST" : "GET",
      headers: { "Content-Type": "application/json", ...(token.current ? { Authorization: `Bearer ${token.current}` } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store", signal: AbortSignal.timeout(15_000),
    });
    if (response.status === 401) {
      token.current = null;
      setProposal(null);
      setGoal(null);
      throw new Error("Your demo session expired. Create a new proposal to start again.");
    }
    if (!response.ok) throw new Error("The request could not be confirmed. Check the backend connection and retry.");
    return response.json();
  }

  async function propose() {
    setBusy(true); setError("");
    try {
      if (!token.current) token.current = (await call("sessions", {})).session_token;
      setProposal(await call("goals/proposals", { daily_gallons: Number(gallons) }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Request failed. Please retry.");
    } finally { setBusy(false); }
  }

  async function decide(decision: "approve" | "reject") {
    if (!proposal) return;
    setBusy(true); setError("");
    try {
      const result: Proposal = await call(`approvals/${proposal.approval_id}/decision`, { decision });
      setProposal(result);
      if (result.status === "approved") setGoal(result.arguments.daily_gallons);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Decision could not be confirmed. Retry safely.");
    } finally { setBusy(false); }
  }

  return <section aria-labelledby="goal-heading" className="rounded-2xl border border-white/10 bg-[#0a1521] p-5">
    <p className="text-xs text-cyan-200">Manual approval demo · no live agent</p>
    <h2 id="goal-heading" className="mt-2 text-lg font-semibold">Conservation goal</h2>
    <p className="mt-2 text-sm leading-6 text-slate-300">Propose a daily target, then review it before approving. This changes only your temporary demo goal, not household equipment.</p>
    <p className="mt-3 text-sm text-slate-200">Approved goal: {goal === null ? "None this session" : `${goal} gallons/day`}</p>
    <form className="mt-4 space-y-3" onSubmit={(event) => { event.preventDefault(); void propose(); }}>
      <label htmlFor="daily-goal" className="block text-sm text-slate-200">Daily target (gallons)</label>
      <input id="daily-goal" type="number" required min="0.01" max="10000" step="0.01" value={gallons}
        onChange={(event) => setGallons(event.target.value)} disabled={busy || proposal?.status === "approval_required"}
        className="w-full rounded-lg border border-white/20 bg-[#07111b] px-3 py-2 text-white focus-visible:outline-2 focus-visible:outline-cyan-300" />
      <button className={button} disabled={busy || proposal?.status === "approval_required"}>Review proposed goal</button>
    </form>
    <div role="status" aria-live="polite" aria-atomic="true" className="mt-4 text-sm text-slate-200">
      {busy ? "Waiting for the server…" : proposal && <>
        <p>{proposal.summary}</p>
        <p className="mt-2">{({ approval_required: "Awaiting your approval. Expires after ten minutes.", approved: "Approved and applied to this demo session.", rejected: "Rejected. Your goal was not changed.", expired: "Proposal expired. Create a new proposal.", conflict: "Your goal changed since this proposal. Create a new proposal." })[proposal.status]}</p>
      </>}
    </div>
    {proposal?.status === "approval_required" && <div className="mt-3 flex flex-wrap gap-3">
      <button type="button" className={button} disabled={busy} onClick={() => void decide("approve")}>Approve goal</button>
      <button type="button" className={button} disabled={busy} onClick={() => void decide("reject")}>Reject</button>
    </div>}
    {error && <p role="alert" className="mt-3 text-sm text-amber-200">{error}</p>}
    <p className="mt-4 text-xs leading-5 text-slate-400">Session lasts up to one hour. Reloading starts fresh; goals are not saved permanently. Live AI recommendations are not connected yet.</p>
  </section>;
}
