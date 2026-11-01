"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import { BillFields } from "../../components/bill-fields";
import { DemoClient } from "../demo/demo-client";
import { comparisonReducer, initialComparisonState } from "./comparison-state";
import { ComparisonSummary } from "./comparison-summary";

export function ComparisonEntry({ client: providedClient }: { client?: DemoClient } = {}) {
  const [client] = useState(() => providedClient ?? new DemoClient());
  const [state, dispatch] = useReducer(comparisonReducer, false, initialComparisonState);
  const working = useRef(false);
  const pendingFocus = useRef<string | null>(null);
  const errorBox = useRef<HTMLParagraphElement>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => { if (state.error) errorBox.current?.focus(); }, [state.error]);
  useEffect(() => {
    if (state.result) {
      resultHeading.current?.focus({ preventScroll: true });
      resultHeading.current?.scrollIntoView({ block: "start", behavior: "instant" });
    }
  }, [state.result]);
  useEffect(() => {
    if (pendingFocus.current) {
      document.getElementById(pendingFocus.current)?.focus();
      pendingFocus.current = null;
    }
  }, [state.items]);

  async function submit() {
    if (working.current) return;
    dispatch({ type: "start" });
    if (!state.sameHousehold) return;
    working.current = true;
    try {
      const result = await client.compareBills(state.items.map((item) => item.draft));
      dispatch({ type: "success", result });
    } catch (cause) {
      dispatch({ type: "failure", message: cause instanceof Error ? cause.message : "Your bills could not be compared. Please submit again later." });
    } finally { working.current = false; }
  }

  return <>
    <section aria-labelledby="comparison-entry-heading" className="min-w-0 pb-8">
      <h2 id="comparison-entry-heading" tabIndex={-1}
        className="scroll-mt-6 text-2xl font-semibold focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus">Your bills</h2>
      <p className="mt-3 max-w-2xl text-sm leading-6 text-ink-secondary">Enter 2 to 12 bills from the same household and meter. Calculation does not use AI or save a bill history. Leave out personal details.</p>
      <form method="post" autoComplete="off" className="mt-5" aria-busy={state.busy}
        onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <fieldset disabled={state.busy} className="min-w-0">
          <legend className="sr-only">Bills to compare</legend>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="ui-button ui-button-secondary" onClick={() => {
              if (working.current) return;
              pendingFocus.current = "comparison-entry-heading";
              dispatch({ type: "replace", example: true });
            }}>Use example bills</button>
            <button type="button" className="ui-button ui-button-secondary" onClick={() => {
              if (working.current) return;
              pendingFocus.current = "comparison-entry-heading";
              dispatch({ type: "replace", example: false });
            }}>Clear all bills</button>
          </div>
          {state.example && <p className="mt-3 text-sm leading-6 text-ink-secondary">Example values; not your household data. Clear all bills before entering your own history.</p>}
          <div className="mt-6 grid gap-x-8 lg:grid-cols-2">
            {state.items.map((item, index) => <fieldset key={item.id} className="min-w-0 space-y-5 border-t border-rule pb-6 pt-4">
              <legend className="px-1 text-lg font-semibold">Bill {index + 1}</legend>
              <BillFields idPrefix={`comparison-${item.id}`} draft={item.draft} onChange={(field, value) => {
                if (!working.current) dispatch({ type: "edit", id: item.id, field, value });
              }} />
              {state.items.length > 2 && <button type="button" className="ui-button ui-button-secondary"
                aria-label={`Remove bill ${index + 1}`} onClick={() => {
                  if (working.current) return;
                  const neighbor = state.items[index === 0 ? 1 : index - 1];
                  pendingFocus.current = `comparison-${neighbor.id}-start`;
                  dispatch({ type: "remove", id: item.id });
                }}>Remove bill</button>}
            </fieldset>)}
          </div>
          {state.items.length < 12 ? <button type="button" className="ui-button ui-button-secondary" onClick={() => {
            if (working.current) return;
            pendingFocus.current = `comparison-${state.nextId}-start`;
            dispatch({ type: "add" });
          }}>Add another bill</button> : <p className="text-sm text-ink-secondary">Maximum of 12 bills reached. Remove a bill to add another.</p>}
          <label className="mt-5 flex min-h-11 items-start gap-3 text-sm leading-6 text-ink-secondary">
            <input type="checkbox" required checked={state.sameHousehold} className="mt-1 size-4 shrink-0 accent-accent"
              onChange={(event) => { if (!working.current) dispatch({ type: "confirm", value: event.target.checked }); }} />
            These bills describe the same household and meter.
          </label>
          <button className="ui-button ui-button-primary mt-3 w-full sm:w-auto">{state.busy ? "Comparing bills…" : "Compare bills"}</button>
        </fieldset>
      </form>
      <p role="status" className="mt-3 text-sm text-ink-secondary">{state.busy ? "Calculating the comparison…" : state.result ? `Compared ${state.result.bills.length} bills. Results are below.` : ""}</p>
      {state.error && <p ref={errorBox} tabIndex={-1} role="alert"
        className="mt-3 rounded-lg border border-warning bg-warning-soft p-3 text-sm leading-6 text-warning focus-visible:outline-2 focus-visible:outline-warning">{state.error}</p>}
      <p className="mt-4 text-xs leading-5 text-muted">Editing, adding or removing a bill clears the previous comparison. Reloading clears all entries.</p>
    </section>
    <ComparisonSummary result={state.result} example={state.example} headingRef={resultHeading} />
  </>;
}
