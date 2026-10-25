"use client";

import { useEffect, useRef, useState } from "react";
import type { ManualBill } from "@/lib/bills";
import { DemoClient } from "../demo/demo-client";

export function BillAssistant({ client, bill, isExample, onBusyChange }: {
  client: DemoClient; bill: ManualBill; isExample: boolean; onBusyChange: (busy: boolean) => void;
}) {
  const [question, setQuestion] = useState("");
  const [share, setShare] = useState(false);
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<{ question: string; text: string } | null>(null);
  const [error, setError] = useState("");
  const working = useRef(false);
  const errorBox = useRef<HTMLParagraphElement>(null);
  useEffect(() => { if (error) errorBox.current?.focus(); }, [error]);

  async function ask() {
    if (working.current || !share || !question.trim()) return;
    working.current = true; onBusyChange(true); setBusy(true); setError(""); setAnswer(null);
    const text = question.trim();
    try {
      const reply = await client.askBill(text, bill, isExample, share);
      if (reply.status === "answer") {
        setAnswer({ question: text, text: reply.answer }); setQuestion("");
      } else {
        setError(reply.status === "refused" ? "AquaMind could not answer this question. Try a question about the entered bill." :
          "AquaMind could not complete this bill question. Your calculation is unchanged; there is no automatic retry.");
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : "The bill question could not be confirmed."); }
    finally { working.current = false; setBusy(false); onBusyChange(false); }
  }

  return <div className="mt-6 border-t border-white/10 pt-5">
    <h3 id="bill-assistant-heading" className="font-semibold">Ask about this bill (optional)</h3>
    <p id="bill-sharing-help" className="mt-2 text-sm leading-6 text-slate-300">Only if you choose to ask, your question, entered bill fields and normalized values will be sent to OpenAI. Live answers use paid API requests. No document is uploaded. Leave names, addresses and account numbers out of your question.</p>
    <p className="mt-2 text-xs leading-5 text-slate-400">Each question stands alone and uses only this bill. Editing or clearing the bill removes the answer and resets sharing consent. No bill history is saved here; provider retention is governed by <a href="https://developers.openai.com/api/docs/guides/your-data" target="_blank" rel="noopener noreferrer" className="underline decoration-slate-500 underline-offset-2 focus-visible:outline-2 focus-visible:outline-cyan-300">OpenAI&apos;s API data policy</a>.</p>
    <form method="post" autoComplete="off" aria-labelledby="bill-assistant-heading" className="mt-4 space-y-4"
      onSubmit={(event) => { event.preventDefault(); void ask(); }}>
      <label htmlFor="bill-question" className="block text-sm text-slate-200">Your bill question
        <textarea id="bill-question" required rows={3} maxLength={2000} value={question} disabled={busy}
          placeholder="What does this daily average tell me, and what would help me investigate further?"
          onChange={(event) => setQuestion(event.target.value)}
          className="mt-2 w-full resize-y rounded-lg border border-white/20 bg-[#07111b] px-3 py-2.5 text-base text-white placeholder:text-slate-500 focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:opacity-60" />
      </label>
      <label className="flex items-start gap-3 text-sm leading-6 text-slate-200">
        <input type="checkbox" required checked={share} disabled={busy} aria-describedby="bill-sharing-help"
          onChange={(event) => setShare(event.target.checked)} className="mt-1 size-4 shrink-0 accent-cyan-300 focus-visible:outline-2 focus-visible:outline-cyan-300" />
        Share this bill and my question with OpenAI for bill-only answers.
      </label>
      <button disabled={busy || !share || !question.trim()}
        className="rounded-lg border border-cyan-300/30 bg-cyan-300/10 px-4 py-3 text-sm font-semibold text-cyan-100 hover:bg-cyan-300/20 focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:opacity-50">
        {busy ? "Waiting for AquaMind…" : "Ask with this bill"}
      </button>
    </form>
    <p role="status" className="mt-3 text-sm text-slate-300">{busy ? "Waiting for the bill-only answer. Your bill is locked while this request runs." : answer ? "Bill-only answer ready below." : ""}</p>
    {error && <p ref={errorBox} tabIndex={-1} role="alert" className="mt-3 rounded-lg border border-amber-300/25 p-3 text-sm leading-6 text-amber-200 focus-visible:outline-2 focus-visible:outline-amber-300">{error}</p>}
    {answer && <article aria-label="Bill-only answer" aria-live="polite" className="mt-4 rounded-xl border border-cyan-300/20 bg-cyan-300/5 p-4 text-sm">
      <p className="text-xs text-cyan-200">{isExample ? "Example bill" : "Entered bill"} · Limited evidence</p>
      <p className="mt-3 whitespace-pre-wrap break-words text-slate-300">You: {answer.question}</p>
      <p className="mt-3 whitespace-pre-wrap break-words leading-6 text-slate-100">{answer.text}</p>
    </article>}
  </div>;
}
