// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import corpus from "../../../../../evals/fixtures/bill-comparison-contract-v1.json";
import { createBillComparisonEntries } from "../../lib/bill-comparison";
import { ComparisonEntry } from "./comparison-entry";

const fixture = corpus.cases[0];
const token = "c".repeat(43);
type Call = { path: string; options: RequestInit };
let root: Root, container: HTMLDivElement, calls: Call[];
let compare: () => Promise<Response>;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => { resolve = yes; });
  return { promise, resolve };
}
function button(text: string) {
  const element = [...container.querySelectorAll<HTMLButtonElement>("button")]
    .find((item) => item.textContent?.trim() === text || item.getAttribute("aria-label") === text);
  if (!element) throw new Error(`Missing button: ${text}`);
  return element;
}
function field(id: string) {
  const element = container.querySelector<HTMLInputElement | HTMLSelectElement>(`#${id}`);
  if (!element) throw new Error(`Missing field: ${id}`);
  return element;
}
const confirmation = () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
const result = () => container.querySelector("#comparison-result-heading")!;
const count = (suffix: string) => calls.filter(({ path }) => path.endsWith(suffix)).length;
async function click(element: HTMLElement) { await act(async () => element.click()); }
async function change(id: string, value: string) {
  const element = field(id);
  await act(async () => {
    const prototype = element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
async function submitDirectly() {
  await act(async () => container.querySelector("form")!
    .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
}
async function populated() {
  await act(async () => root.render(<ComparisonEntry />));
  await click(button("Add another bill"));
  const suffixes = { period_start: "start", period_end_exclusive: "end", usage: "usage",
    usage_unit: "unit", water_charge: "water-charge", sewer_charge: "sewer-charge", currency: "currency" };
  for (const [index, draft] of fixture.drafts.entries()) {
    for (const key of Object.keys(suffixes) as (keyof typeof suffixes)[]) {
      await change(`comparison-${index}-${suffixes[key]}`, draft[key]);
    }
  }
}

beforeEach(() => {
  calls = [];
  compare = async () => Response.json(fixture.response);
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn(async (url: string, options: RequestInit = {}) => {
    const path = String(url); calls.push({ path, options });
    if (path === "/api/aquamind/v1/sessions") return Response.json({ session_token: token });
    if (path === "/api/aquamind/v1/bills/compare") return compare();
    throw new Error(`Unexpected request: ${path}`);
  }));
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  vi.restoreAllMocks(); vi.unstubAllGlobals();
});

describe("bill comparison interactions", () => {
  it("requires confirmation, submits once while locked, and invalidates results when bills change", async () => {
    const pending = deferred<Response>(); compare = () => pending.promise;
    await populated();
    await submitDirectly(); // React guard also protects a submission bypassing native validation.
    expect(calls).toHaveLength(0);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("same household");
    await click(confirmation());
    const submit = button("Compare bills");
    await act(async () => { submit.click(); submit.click(); });
    await submitDirectly();
    expect(count("/bills/compare")).toBe(1);
    expect(container.querySelector("form")?.getAttribute("aria-busy")).toBe("true");
    expect(field("comparison-0-usage").matches(":disabled")).toBe(true);
    expect(button("Remove bill 3").matches(":disabled")).toBe(true);
    const sent = calls.find(({ path }) => path.endsWith("/bills/compare"))!;
    expect(JSON.parse(String(sent.options.body))).toEqual({ bills: createBillComparisonEntries(fixture.drafts) });
    expect(sent.options.credentials).toBe("omit");
    expect(sent.options.headers).toMatchObject({ Authorization: `Bearer ${token}` });
    await act(async () => pending.resolve(Response.json(fixture.response)));
    expect(result().textContent).toBe("Your bill comparison");
    expect(document.activeElement).toBe(result());
    expect(container.textContent).toContain("34.83%");
    expect(container.textContent).toContain("31 days between supplied periods are excluded");
    const rows = container.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(3);
    expect(rows[0].textContent).toContain("2024-01-01");
    expect(rows[0].textContent).toContain("Sewer: Unknown");
    expect(rows[2].textContent).toContain("Subtotal: $0.00");

    await change("comparison-0-usage", "6100");
    expect(result().textContent).toBe("Compare supplied periods");
    expect(container.querySelector("table")).toBeNull();
    expect(confirmation().checked).toBe(false);
    expect(count("/bills/compare")).toBe(1);
    await click(button("Add another bill"));
    expect(document.activeElement?.id).toBe("comparison-3-start");
    await click(button("Remove bill 4"));
    expect(document.activeElement?.id).toBe("comparison-2-start");
    await click(button("Clear all bills"));
    expect(document.activeElement?.id).toBe("comparison-entry-heading");
    expect(field("comparison-0-usage").value).toBe("");
    expect(container.querySelectorAll('input[name="usage"]')).toHaveLength(2);
  });

  it("focuses overlap validation without creating a session or sending bills", async () => {
    await populated();
    await change("comparison-1-start", "2024-04-01");
    await change("comparison-1-end", "2024-05-01");
    await click(confirmation()); await click(button("Compare bills"));
    const error = container.querySelector('[role="alert"]');
    expect(error?.textContent).toContain("must not overlap or repeat");
    expect(document.activeElement).toBe(error);
    expect(calls).toHaveLength(0);
    expect(button("Compare bills").matches(":disabled")).toBe(false);
  });

  it("retains entries after session expiry and waits for explicit resubmission with a new session", async () => {
    compare = async () => Response.json({ detail: "private provider detail" }, { status: 401 });
    await populated(); await click(confirmation()); await click(button("Compare bills"));
    const error = container.querySelector('[role="alert"]');
    expect(error?.textContent).toContain("session expired");
    expect(document.activeElement).toBe(error);
    expect(container.textContent).not.toContain("private provider detail");
    expect(field("comparison-0-usage").value).toBe("6000");
    expect(count("/sessions")).toBe(1); expect(count("/bills/compare")).toBe(1);
    expect(container.querySelector("table")).toBeNull();
    await act(async () => {});
    expect(count("/bills/compare")).toBe(1);
    compare = async () => Response.json(fixture.response);
    await click(button("Compare bills"));
    expect(count("/sessions")).toBe(2); expect(count("/bills/compare")).toBe(2);
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(result().textContent).toBe("Your bill comparison");
  });
});
