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

  return <div className="mt-6 border-t border-rule pt-5">
    <h3 id="bill-assistant-heading" className="font-semibold">Ask about this bill (optional)</h3>
    <p id="bill-sharing-help" className="mt-2 text-sm leading-6 text-ink-secondary">Your bill details and question are sent to an external AI service. Leave out personal information.</p>
    <p className="mt-2 text-xs leading-5 text-muted">Each question uses only this bill. Editing or clearing removes the answer and resets sharing consent. No bill history is saved. <a href="https://developers.openai.com/api/docs/guides/your-data" target="_blank" rel="noopener noreferrer" className="underline decoration-control-border underline-offset-2 focus-visible:outline-2 focus-visible:outline-focus">Data policy</a></p>
    <form method="post" autoComplete="off" aria-labelledby="bill-assistant-heading" className="mt-4 space-y-4"
      onSubmit={(event) => { event.preventDefault(); void ask(); }}>
      <label htmlFor="bill-question" className="block text-sm text-ink-secondary">Your bill question
        <textarea id="bill-question" required rows={3} maxLength={2000} value={question} disabled={busy}
          placeholder="What does this daily average tell me, and what would help me investigate further?"
          onChange={(event) => setQuestion(event.target.value)}
          className="ui-field mt-2 resize-y" />
      </label>
      <label className="flex items-start gap-3 text-sm leading-6 text-ink-secondary">
        <input type="checkbox" required checked={share} disabled={busy} aria-describedby="bill-sharing-help"
          onChange={(event) => setShare(event.target.checked)} className="mt-1 size-4 shrink-0 accent-accent focus-visible:outline-2 focus-visible:outline-focus" />
        Allow AI to read this bill and answer my question.
      </label>
      <button disabled={busy || !share || !question.trim()}
        className="ui-button ui-button-secondary">
        {busy ? "Waiting for AquaMind…" : "Ask with this bill"}
      </button>
    </form>
    <p role="status" className="mt-3 text-sm text-ink-secondary">{busy ? "Waiting for the bill-only answer. Your bill is locked while this request runs." : answer ? "Bill-only answer ready below." : ""}</p>
    {error && <p ref={errorBox} tabIndex={-1} role="alert" className="mt-3 rounded-lg border border-warning p-3 text-sm leading-6 text-warning focus-visible:outline-2 focus-visible:outline-warning">{error}</p>}
    {answer && <article aria-label="Bill-only answer" aria-live="polite" className="mt-4 rounded-xl border border-rule bg-accent-soft p-4 text-sm">
      <p className="text-xs text-ink-secondary">{isExample ? "Example bill" : "Entered bill"}; Limited evidence</p>
      <p className="mt-3 whitespace-pre-wrap break-words text-ink-secondary">You: {answer.question}</p>
      <p className="mt-3 whitespace-pre-wrap break-words leading-6 text-ink">{answer.text}</p>
    </article>}
  </div>;
}
