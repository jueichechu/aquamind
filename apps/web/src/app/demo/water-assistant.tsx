"use client";

import { useEffect, useRef, useState } from "react";
import { DemoClient, SessionExpired, type AgentReply, type Proposal, type ToolEvent } from "./demo-client";

const button = "rounded-lg border border-cyan-300/30 px-4 py-2 text-sm text-cyan-100 hover:bg-cyan-300/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:opacity-50";
type Message = { who: "You" | "AquaMind"; text: string; tools?: ToolEvent[] };
const outcomeText: Record<Exclude<AgentReply["status"], "answer">, string> = {
  approval_required: "A goal proposal is ready for review below. No goal has been changed.",
  refused: "I couldn’t answer that request. Try a question about household water use.",
  limit_reached: "This question reached the demo’s processing limit. No answer was confirmed. Try a simpler question.",
  unavailable: "The assistant is unavailable for this question. No answer was confirmed. You can still try the manual goal form.",
  unconfirmed: "The request could not be confirmed. It won’t be retried automatically. Goals still need your separate approval.",
};
const proposalText: Record<Proposal["status"], string> = {
  approval_required: "Awaiting your decision. Proposals expire within ten minutes; the server checks expiry when you decide.",
  approved: "Approved and applied to this demo session.",
  rejected: "Rejected. This proposal did not change your goal.",
  expired: "Proposal expired. Ask again or create a new proposal.",
  conflict: "Your goal changed since this proposal. Create a new proposal.",
};
const toolLabels: Record<string, string> = {
  get_weather_context: "Synthetic weather", get_utility_rate: "Illustrative utility rate",
  estimate_water_cost: "Water-cost calculation", estimate_conservation_savings: "Savings calculation",
  set_conservation_goal: "Goal proposal",
};

export function WaterAssistant() {
  const [client] = useState(() => new DemoClient());
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [gallons, setGallons] = useState("150");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [continuation, setContinuation] = useState<string | null>(null);
  const [goal, setGoal] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const busyRef = useRef(false);
  const log = useRef<HTMLDivElement>(null);
  const pending = proposal?.status === "approval_required";

  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [messages]);

  async function perform(operation: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true); setError("");
    try { await operation(); }
    catch (cause) {
      if (cause instanceof SessionExpired) { setProposal(null); setGoal(null); setMessages([]); setContinuation(null); }
      setError(cause instanceof Error ? cause.message : "The request could not be confirmed.");
    } finally { busyRef.current = false; setBusy(false); }
  }

  function showProposal(result: Proposal) {
    setProposal(result);
    if (result.status === "approved") setGoal(result.arguments.daily_gallons);
  }

  function showReply(reply: AgentReply) {
    setMessages((previous) => [...previous, { who: "AquaMind" as const,
      text: reply.status === "answer" ? reply.answer : outcomeText[reply.status], tools: reply.tool_trace }].slice(-16));
  }

  async function continueDecision(result: Proposal) {
    const reply = await client.continueAfterDecision(result.approval_id);
    showReply(reply);
    setContinuation(null);
  }

  async function resolveProposal(result: Proposal) {
    showProposal(result); // Keep the confirmed decision even if the model follow-up fails.
    if (continuation === result.approval_id && result.status !== "approval_required") {
      setMessages((previous) => [...previous, { who: "You" as const,
        text: `Goal review: ${result.status}. ${result.summary}` }].slice(-16));
      await continueDecision(result);
    }
  }

  async function send() {
    if (pending || !question.trim()) return;
    const text = question.trim();
    await perform(async () => {
      setContinuation(null);
      setMessages((previous) => [...previous, { who: "You" as const, text }].slice(-16));
      const reply = await client.ask(text);
      setQuestion("");
      showReply(reply);
      setContinuation(reply.pending_approval?.approval_id ?? null);
      if (reply.pending_approval) showProposal(reply.pending_approval);
    });
  }

  return <section aria-labelledby="assistant-heading" className="min-w-0 self-start rounded-2xl border border-white/10 bg-[#0a1521] p-5">
    <p className="text-xs text-cyan-200">AI text assistant · local demo</p>
    <h2 id="assistant-heading" className="mt-2 text-lg font-semibold">Ask AquaMind</h2>
    <p className="mt-2 text-sm leading-6 text-slate-300">Explore demo rates, savings, synthetic weather, or a daily goal. The meter chart is not shared with chat yet.</p>
    <p className="mt-2 text-xs leading-5 text-slate-400">New questions stand on their own. After you review an AI goal proposal, AquaMind can explain the confirmed result. Questions are sent to OpenAI; avoid personal information.</p>

    <div ref={log} role="log" aria-label="Conversation" aria-live="polite" className="mt-4 max-h-[420px] space-y-3 overflow-y-auto overscroll-contain">
      {messages.map((message, index) => <article key={index} className={`rounded-xl p-3 text-sm ${message.who === "You" ? "bg-white/5" : "border border-cyan-300/15 bg-cyan-300/5"}`}>
        <p className="text-xs font-semibold text-cyan-100">{message.who}</p>
        <p className="mt-2 whitespace-pre-wrap break-words leading-6 text-slate-200">{message.text}</p>
        {!!message.tools?.length && <details className="mt-3 text-xs text-slate-300">
          <summary className="cursor-pointer rounded focus-visible:outline-2 focus-visible:outline-cyan-300">Tools used</summary>
          <ul className="mt-2 space-y-1">{message.tools.map((tool, position) => <li key={position} className="break-words">
            {toolLabels[tool.tool_name] ?? "Tool"}: {tool.status.replaceAll("_", " ")} · {Math.round(tool.elapsed_ms)} ms
          </li>)}</ul>
        </details>}
      </article>)}
    </div>
    <form className="mt-4 space-y-3" onSubmit={(event) => { event.preventDefault(); void send(); }}>
      <label htmlFor="water-question" className="block text-sm text-slate-200">Your water question</label>
      <textarea id="water-question" required rows={3} maxLength={2000} value={question}
        placeholder="What would 1,000 gallons cost at the demo rate?" disabled={busy || pending}
        onChange={(event) => setQuestion(event.target.value)}
        className="w-full resize-y rounded-lg border border-white/20 bg-[#07111b] px-3 py-2 text-sm text-white placeholder:text-slate-500 focus-visible:outline-2 focus-visible:outline-cyan-300" />
      <button className={button} disabled={busy || pending || !question.trim()}>Send question</button>
    </form>

    <div className="mt-6 border-t border-white/10 pt-5">
      <h3 id="goal-heading" className="font-semibold">Conservation goal</h3>
      <p className="mt-2 text-sm text-slate-200">Approved goal: {goal === null ? "None this session" : `${goal} gallons/day`}</p>
      <p className="mt-2 text-xs leading-5 text-slate-400">Only your explicit approval applies a temporary goal. No household equipment is controlled.</p>
      <details className="mt-3">
        <summary className="cursor-pointer rounded text-sm text-cyan-100 focus-visible:outline-2 focus-visible:outline-cyan-300">Enter a goal manually</summary>
        <form className="mt-3 space-y-3" onSubmit={(event) => { event.preventDefault();
          if (!pending) void perform(async () => { showProposal(await client.propose(Number(gallons))); setContinuation(null); }); }}>
          <label htmlFor="daily-goal" className="block text-sm text-slate-200">Daily target (gallons)</label>
          <input id="daily-goal" type="number" required min="0.01" max="10000" step="0.01" value={gallons}
            onChange={(event) => setGallons(event.target.value)} disabled={busy || pending}
            className="w-full rounded-lg border border-white/20 bg-[#07111b] px-3 py-2 text-white focus-visible:outline-2 focus-visible:outline-cyan-300" />
          <button className={button} disabled={busy || pending}>Review proposed goal</button>
        </form>
      </details>
      {proposal && <div aria-labelledby="goal-heading" className="mt-4 rounded-xl border border-cyan-300/20 p-3 text-sm text-slate-200">
        <p className="font-medium">{proposal.summary}</p>
        <p className="mt-2">{proposalText[proposal.status]}</p>
        {pending && <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className={button} disabled={busy}
            onClick={() => void perform(async () => resolveProposal(await client.decide(proposal, "approve")))}>Approve goal</button>
          <button type="button" className={button} disabled={busy}
            onClick={() => void perform(async () => resolveProposal(await client.decide(proposal, "reject")))}>Reject</button>
          <button type="button" className={button} disabled={busy}
            onClick={() => void perform(async () => resolveProposal(await client.review(proposal)))}>Refresh proposal</button>
        </div>}
      </div>}
      {continuation && proposal && !pending && <button type="button" className={`${button} mt-3`} disabled={busy}
        onClick={() => void perform(async () => continueDecision(proposal))}>Check assistant follow-up</button>}
    </div>
    <p role="status" aria-live="polite" aria-atomic="true" className="mt-3 text-sm text-slate-300">
      {busy ? "Waiting for AquaMind…" : pending ? "Review the pending proposal before sending another question." : proposal ? proposalText[proposal.status] : ""}
    </p>
    {error && <p role="alert" className="mt-3 text-sm text-amber-200">{error}</p>}
    <p className="mt-4 text-xs leading-5 text-slate-400">Session lasts up to one hour. Reloading starts fresh; goals and questions are not saved permanently.</p>
  </section>;
}
