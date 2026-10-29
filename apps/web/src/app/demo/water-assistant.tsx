"use client";

import { useEffect, useRef, useState } from "react";
import { SCENARIOS, type ScenarioId } from "@/lib/water";
import { DemoClient, SessionExpired, type AgentReply, type Proposal, type ToolEvent } from "./demo-client";

const button = "ui-button ui-button-secondary";
type Message = { who: "You" | "AquaMind"; text: string; scenarioId: ScenarioId; tools?: ToolEvent[] };
type Continuation = { approvalId: string; scenarioId: ScenarioId };
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
  get_meter_summary: "Synthetic meter summary", get_meter_series: "Synthetic meter readings",
  detect_water_anomaly: "Experimental anomaly check",
};

export function WaterAssistant({ scenarioId }: { scenarioId: ScenarioId }) {
  const [client] = useState(() => new DemoClient());
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [gallons, setGallons] = useState("150");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [continuation, setContinuation] = useState<Continuation | null>(null);
  const [proposalScenario, setProposalScenario] = useState<ScenarioId | null>(null);
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
      if (cause instanceof SessionExpired) { setProposal(null); setGoal(null); setMessages([]); setContinuation(null); setProposalScenario(null); }
      setError(cause instanceof Error ? cause.message : "The request could not be confirmed.");
    } finally { busyRef.current = false; setBusy(false); }
  }

  function showProposal(result: Proposal) {
    setProposal(result);
    if (result.status === "approved") setGoal(result.arguments.daily_gallons);
  }

  function showReply(reply: AgentReply, selectedScenario: ScenarioId) {
    setMessages((previous) => [...previous, { who: "AquaMind" as const,
      text: reply.status === "answer" ? reply.answer : outcomeText[reply.status],
      scenarioId: selectedScenario, tools: reply.tool_trace }].slice(-16));
  }

  async function continueDecision(result: Proposal, selectedScenario: ScenarioId) {
    const reply = await client.continueAfterDecision(result.approval_id);
    showReply(reply, selectedScenario);
    setContinuation(null);
  }

  async function resolveProposal(result: Proposal) {
    showProposal(result); // Keep the confirmed decision even if the model follow-up fails.
    if (continuation?.approvalId === result.approval_id && result.status !== "approval_required") {
      setMessages((previous) => [...previous, { who: "You" as const,
        text: `Goal review: ${result.status}. ${result.summary}`, scenarioId: continuation.scenarioId }].slice(-16));
      await continueDecision(result, continuation.scenarioId);
    }
  }

  async function send() {
    if (pending || !question.trim()) return;
    const text = question.trim();
    const selectedScenario = scenarioId;
    await perform(async () => {
      setContinuation(null);
      setMessages((previous) => [...previous, { who: "You" as const, text, scenarioId: selectedScenario }].slice(-16));
      const reply = await client.ask(text, selectedScenario);
      setQuestion("");
      showReply(reply, selectedScenario);
      setContinuation(reply.pending_approval ? { approvalId: reply.pending_approval.approval_id, scenarioId: selectedScenario } : null);
      if (reply.pending_approval) { showProposal(reply.pending_approval); setProposalScenario(selectedScenario); }
    });
  }

  return <section aria-labelledby="assistant-heading" className="min-w-0 self-start border-t border-rule pt-6 xl:border-t-0 xl:border-l xl:pt-0 xl:pl-6">
    <h2 id="assistant-heading" tabIndex={-1} className="scroll-mt-4 text-lg font-semibold focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus">Ask AquaMind</h2>
    <p className="mt-1 text-xs text-muted">AI text assistant, local demo</p>
    <p className="mt-2 text-sm leading-6 text-ink-secondary">Explore the selected synthetic meter readings and weather, demo rates, savings, or a daily goal. Model findings are experimental and do not prove a physical leak.</p>
    <p className="mt-3 text-sm font-medium text-ink">Selected scenario: {SCENARIOS[scenarioId].title}</p>
    <p className="mt-2 text-xs leading-5 text-muted">New questions stand on their own and use the scenario selected when sent. Earlier replies and goal follow-ups keep their original scenario. Questions and requested synthetic evidence are sent to an external AI service; avoid personal information.</p>

    <div ref={log} role="log" aria-label="Conversation" aria-live="polite" className="mt-4 max-h-[420px] space-y-3 overflow-y-auto overscroll-contain">
      {messages.map((message, index) => <article key={index} className="border-b border-rule py-3 text-sm">
        <p className="text-xs font-semibold text-accent">{message.who}</p>
        <p className="mt-1 text-xs text-muted">Scenario: {SCENARIOS[message.scenarioId].title}</p>
        <p className="mt-2 whitespace-pre-wrap break-words leading-6 text-ink">{message.text}</p>
        {!!message.tools?.length && <details className="mt-3 text-xs text-ink-secondary">
          <summary className="cursor-pointer rounded focus-visible:outline-2 focus-visible:outline-focus">Tools used</summary>
          <ul className="mt-2 space-y-1">{message.tools.map((tool, position) => <li key={position} className="break-words">
            {toolLabels[tool.tool_name] ?? "Tool"}: {tool.status.replaceAll("_", " ")}, {Math.round(tool.elapsed_ms)} ms
          </li>)}</ul>
        </details>}
      </article>)}
    </div>
    <form className="mt-4 space-y-3" onSubmit={(event) => { event.preventDefault(); void send(); }}>
      <label htmlFor="water-question" className="block text-sm text-ink">Your water question</label>
      <textarea id="water-question" required rows={3} maxLength={2000} value={question}
        placeholder="How does this day compare with the six-day baseline?" disabled={busy || pending}
        onChange={(event) => setQuestion(event.target.value)}
        className="ui-field resize-y" />
      <button className="ui-button ui-button-primary" aria-busy={busy} disabled={busy || pending || !question.trim()}>Send question</button>
    </form>

    <div className="mt-6 border-t border-rule pt-5">
      <h3 id="goal-heading" className="font-semibold">Conservation goal</h3>
      <p className="mt-2 text-sm text-ink">Approved goal: {goal === null ? "None this session" : `${goal} gallons/day`}</p>
      <p className="mt-2 text-xs leading-5 text-muted">Only your explicit approval applies a temporary goal. No household equipment is controlled.</p>
      <details className="mt-3">
        <summary className="cursor-pointer rounded text-sm text-accent focus-visible:outline-2 focus-visible:outline-focus">Enter a goal manually</summary>
        <form className="mt-3 space-y-3" onSubmit={(event) => { event.preventDefault();
          if (!pending) void perform(async () => { showProposal(await client.propose(Number(gallons))); setContinuation(null); setProposalScenario(null); }); }}>
          <label htmlFor="daily-goal" className="block text-sm text-ink">Daily target (gallons)</label>
          <input id="daily-goal" type="number" required min="0.01" max="10000" step="0.01" value={gallons}
            onChange={(event) => setGallons(event.target.value)} disabled={busy || pending}
            className="ui-field" />
          <button className={button} disabled={busy || pending}>Review proposed goal</button>
        </form>
      </details>
      {proposal && <div aria-labelledby="goal-heading" className="mt-4 border-t border-rule pt-4 text-sm text-ink">
        {proposalScenario && <p className="mb-2 text-xs text-muted">Proposed with: {SCENARIOS[proposalScenario].title}</p>}
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
        onClick={() => void perform(async () => continueDecision(proposal, continuation.scenarioId))}>Check assistant follow-up</button>}
    </div>
    <p role="status" aria-live="polite" aria-atomic="true" className="mt-3 text-sm text-ink-secondary">
      {busy ? "Waiting for AquaMind…" : pending ? "Review the pending proposal before sending another question." : proposal ? proposalText[proposal.status] : ""}
    </p>
    {error && <p role="alert" className="mt-3 text-sm text-warning">{error}</p>}
    <p className="mt-4 text-xs leading-5 text-muted">Session lasts up to one hour. Reloading starts fresh; goals and questions are not saved permanently.</p>
  </section>;
}
