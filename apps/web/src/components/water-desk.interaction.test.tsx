// @vitest-environment jsdom

import { File as MemoryFile } from "node:buffer";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WaterDesk } from "./water-desk";

const token = "b".repeat(43);
const requestId = "12345678-abcd-1234-abcd-123456789abc";
const fields = {
  period_start: "2026-06-01", period_end_exclusive: "2026-07-01", usage: "8.5", usage_unit: "ccf",
  water_charge: "45.12", sewer_charge: "0.00", currency: "USD",
};
const imported = () => ({ source: "document_import", needs_review: true, request_id: requestId,
  fields, warnings: [], evidence: { schema_version: 1, reading_type: "unknown", reading_type_page: null,
    fields: Object.fromEntries(Object.keys(fields).map((key) => [key, { kind: "printed", page: 1 }])) } });
const calculated = () => ({ source: "manual_entry", evidence_level: "bill_only", confidence: "limited",
  request_id: requestId, bill: fields, billing_days: 30, total_us_gallons: "6358.441558",
  us_gallons_per_day: "211.948052", water_and_sewer_subtotal: "45.12" });

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

type Call = { path: string; options: RequestInit };
let calls: Call[], root: Root, container: HTMLDivElement;
let readiness: () => Promise<Response>, extraction: () => Promise<Response>, questionReply: () => Promise<Response>;
const answered = () => ({ status: "answer", answer: "A bounded fictional bill-only answer.", pending_approval: null, tool_trace: [] });

const count = (suffix: string) => calls.filter(({ path }) => path.endsWith(suffix)).length;
const posts = () => calls.filter(({ options }) => options.method === "POST");
function button(text: string) {
  const found = [...container.querySelectorAll<HTMLButtonElement>("button")]
    .find((element) => element.textContent?.trim() === text);
  if (!found) throw new Error(`Missing button: ${text}`);
  return found;
}
function input(selector: string) {
  const found = container.querySelector<HTMLInputElement>(selector);
  if (!found) throw new Error(`Missing input: ${selector}`);
  return found;
}
const consent = () => input('.report-share-label input[type="checkbox"]');
const review = () => input('.desk-review input[type="checkbox"][required]');
function progress(title: string) {
  const indicator = container.querySelector('[role="progressbar"]');
  expect(indicator).not.toBeNull();
  expect(indicator?.hasAttribute("aria-valuenow")).toBe(false); // No invented percentage.
  const label = container.querySelector(`#${indicator?.getAttribute("aria-labelledby")}`);
  expect(label?.textContent).toBe(title);
  expect(label?.closest('[role="status"]')?.getAttribute("aria-atomic")).toBe("true");
}
async function click(element: HTMLElement) { await act(async () => element.click()); }
async function settle(assertion: () => void) {
  await vi.waitFor(async () => { await act(async () => {}); assertion(); });
}
async function mount() {
  await act(async () => root.render(<WaterDesk />));
}
async function choose(name = "fictional-private-name.webp") {
  // The real byte encoder runs. Only the DOM file-list assignment is simulated.
  const file = new MemoryFile(["RIFF0000WEBPfictional-water-report"], name, { type: "image/webp" });
  const reading = vi.spyOn(file, "arrayBuffer");
  const element = input('input[type="file"]');
  Object.defineProperty(element, "files", { configurable: true, value: [file] });
  await act(async () => element.dispatchEvent(new Event("change", { bubbles: true })));
  return reading;
}

beforeEach(() => {
  calls = [];
  readiness = async () => Response.json({ status: "ready" });
  extraction = async () => Response.json(imported());
  questionReply = async () => Response.json(answered());
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn(async (url: string, options: RequestInit = {}) => {
    const path = String(url); calls.push({ path, options });
    if (path === "/api/aquamind/v1/bills/readiness") return readiness();
    if (path === "/api/aquamind/v1/sessions") return Response.json({ session_token: token });
    if (path === "/api/aquamind/v1/bills/import") return extraction();
    if (path === "/api/aquamind/v1/bills/normalize") return Response.json(calculated());
    if (path === "/api/aquamind/v1/agent/bill") return questionReply();
    throw new Error(`Unexpected test request: ${path}`);
  }));
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks(); vi.unstubAllGlobals();
});

describe("start-page bill interactions", () => {
  it("waits for readiness and consent, imports once, then requires review before calculation", async () => {
    const starting = deferred<Response>(); readiness = () => starting.promise;
    const paid = deferred<Response>(); extraction = () => paid.promise;
    await mount();
    const reading = await choose();
    await click(consent());
    expect(button("Starting bill analysis…").disabled).toBe(true);
    progress("Starting bill analysis…");
    expect(reading).not.toHaveBeenCalled(); expect(posts()).toHaveLength(0);

    readiness = async () => Response.json({ status: "ready" });
    await act(async () => starting.resolve(Response.json({ status: "ready" })));
    expect(button("Read report").disabled).toBe(false);
    expect(container.querySelector('[role="progressbar"]')).toBeNull();
    expect(posts()).toHaveLength(0); // Becoming ready never submits the file.
    const submit = button("Read report");
    await act(async () => { submit.click(); submit.click(); });
    await settle(() => expect(count("/bills/import")).toBe(1));
    const pending = button("Reading your report…");
    progress("Reading your report…");
    expect(container.querySelector(".report-consent")?.getAttribute("aria-busy")).toBe("true");
    expect(container.querySelector("#report-progress-detail")?.textContent).toContain("You’ll review the details");
    expect(pending.disabled).toBe(true); await click(pending);
    expect(count("/bills/import")).toBe(1);
    const sent = calls.find(({ path }) => path.endsWith("/bills/import"))!;
    expect(JSON.parse(String(sent.options.body))).toEqual({ media_type: "image/webp", share_with_ai: true,
      data_base64: btoa("RIFF0000WEBPfictional-water-report") });
    expect(String(sent.options.body)).not.toContain("fictional-private-name");
    expect(sent.options.credentials).toBe("omit");
    expect(sent.options.headers).toMatchObject({ Authorization: `Bearer ${token}` });
    expect(reading).toHaveBeenCalledTimes(1);

    await act(async () => paid.resolve(Response.json(imported())));
    await settle(() => expect(container.querySelector("#review-heading")).not.toBeNull());
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('[role="progressbar"]')).toBeNull();
    expect(document.activeElement?.id).toBe("review-heading");
    expect(input("#bill-usage").value).toBe("8.5");
    expect(review().checked).toBe(false);
    expect(button("Calculate bill usage").disabled).toBe(true);
    // Even a direct submit event cannot bypass the React review guard.
    await act(async () => container.querySelector(".desk-review form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(count("/bills/normalize")).toBe(0);
    await click(review()); await click(button("Calculate bill usage"));
    await settle(() => expect(container.querySelector('[data-testid="bill-daily-usage"]')?.textContent).toBe("211.948052"));
    expect(count("/bills/normalize")).toBe(1);
    expect(count("/sessions")).toBe(1);
    expect(document.activeElement?.id).toBe("bill-result-heading");
    const breakdown = container.querySelector("#bill-result-heading")!.closest("section")!;
    expect(breakdown.textContent).toContain("2026-06-01 to 2026-07-01 (exclusive); 30 days");

    const usage = input("#bill-usage");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(usage, "9.5");
      usage.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(container.querySelector('[data-testid="bill-daily-usage"]')).toBeNull();
    expect(review().checked).toBe(false);
    expect(button("Calculate bill usage").disabled).toBe(true);
    expect(count("/bills/normalize")).toBe(1);
    await choose("replacement.webp");
    expect(consent().checked).toBe(false);
    expect(container.querySelector("#review-heading")).toBeNull();
    expect(count("/bills/import")).toBe(1);
  });

  it.each(["network", "401", "429", "503", "413", "422", "malformed"])("retains the report and clears consent after %s without replaying extraction", async (failure) => {
    const paid = deferred<Response>(); extraction = () => paid.promise;
    await mount(); await choose(); await click(consent()); await click(button("Read report"));
    await settle(() => expect(count("/bills/import")).toBe(1));
    await act(async () => {
      if (failure === "network") paid.reject(new Error("private provider information"));
      else paid.resolve(Response.json({ detail: "private provider information" },
        failure === "malformed" ? undefined : { status: Number(failure) }));
    });
    await settle(() => expect(container.querySelector('[role="alert"]')?.textContent).toBeTruthy());
    expect(document.activeElement).toBe(container.querySelector('[role="alert"]'));
    expect(container.querySelector("#review-heading")).toBeNull();
    expect(container.textContent).not.toContain("private provider information");
    expect(container.querySelector('[role="progressbar"]')).toBeNull();
    expect(container.querySelector(".report-consent")?.getAttribute("aria-busy")).toBe("false");
    expect(container.querySelector('[role="status"]')?.textContent).not.toContain("Ready to read");
    expect(container.textContent).toContain("fictional-private-name.webp");
    expect(consent().checked).toBe(false);
    expect(button("Read report").disabled).toBe(true);
    await click(button("Read report"));
    expect(count("/bills/import")).toBe(1);
    expect(count("/bills/normalize")).toBe(0);
    await click(button("Remove report"));
    expect(container.textContent).not.toContain("fictional-private-name.webp");
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(button("Choose a report").disabled).toBe(false);
  });

  it("requires fresh consent and an explicit submit to recover an import after session expiry", async () => {
    extraction = async () => Response.json({ detail: "private provider information" }, { status: 401 });
    await mount(); await choose(); await click(consent()); await click(button("Read report"));
    await settle(() => expect(container.querySelector('[role="alert"]')?.textContent).toContain("session expired"));
    expect(count("/sessions")).toBe(1); expect(count("/bills/import")).toBe(1);
    extraction = async () => Response.json(imported());
    await click(consent());
    expect(count("/bills/import")).toBe(1);
    await click(button("Read report"));
    await settle(() => expect(container.querySelector("#review-heading")).not.toBeNull());
    expect(count("/sessions")).toBe(2); expect(count("/bills/import")).toBe(2);
    expect(review().checked).toBe(false);
  });

  it.each(["network", "401", "429", "503", "malformed", "refused", "unconfirmed"])("preserves the calculation and recovers explicitly after a %s bill question", async (failure) => {
    const pending = deferred<Response>(); questionReply = () => pending.promise;
    await mount(); await choose(); await click(consent()); await click(button("Read report"));
    await settle(() => expect(container.querySelector("#review-heading")).not.toBeNull());
    await click(review()); await click(button("Calculate bill usage"));
    await settle(() => expect(container.querySelector("#bill-question")).not.toBeNull());
    const question = container.querySelector<HTMLTextAreaElement>("#bill-question")!;
    const share = input('form[aria-labelledby="bill-assistant-heading"] input[type="checkbox"]');
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(question, "What does this daily average mean?");
      question.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(button("Ask with this bill").disabled).toBe(true);
    await click(share);
    const submit = button("Ask with this bill");
    await act(async () => { submit.click(); submit.click(); });
    expect(count("/agent/bill")).toBe(1);
    expect(input("#bill-usage").matches(":disabled")).toBe(true);
    expect(input('input[type="file"]').disabled).toBe(true);
    expect(question.disabled).toBe(true);
    await act(async () => {
      if (failure === "network") pending.reject(new Error("private provider information"));
      else if (failure === "malformed") pending.resolve(Response.json({ ...answered(), answer: "" }));
      else if (failure === "refused" || failure === "unconfirmed") pending.resolve(Response.json({ ...answered(), status: failure, answer: "" }));
      else pending.resolve(Response.json({ detail: "private provider information" }, { status: Number(failure) }));
    });
    const error = container.querySelector('[role="alert"]');
    expect(error?.textContent).toBeTruthy(); expect(document.activeElement).toBe(error);
    expect(container.textContent).not.toContain("private provider information");
    expect(container.querySelector('[aria-label="Bill-only answer"]')).toBeNull();
    expect(container.querySelector('[data-testid="bill-daily-usage"]')?.textContent).toBe("211.948052");
    expect(question.value).toBe("What does this daily average mean?");
    expect(input("#bill-usage").matches(":disabled")).toBe(false);
    expect(input('input[type="file"]').disabled).toBe(false);
    await act(async () => {});
    expect(count("/agent/bill")).toBe(1);
    questionReply = async () => Response.json(answered());
    if (!share.checked) await click(share);
    await click(button("Ask with this bill"));
    expect(count("/agent/bill")).toBe(2);
    expect(count("/sessions")).toBe(failure === "401" ? 2 : 1);
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('[aria-label="Bill-only answer"]')?.textContent).toContain(answered().answer);
    expect(question.value).toBe("");
  });

  it("rechecks readiness before transmission and retries only that check after startup fails", async () => {
    await mount(); const reading = await choose(); await click(consent());
    const preflight = deferred<Response>(); readiness = () => preflight.promise;
    await click(button("Read report"));
    progress("Starting bill analysis…");
    expect(container.querySelector("#report-progress-detail")?.textContent).toContain("not been sent yet");
    expect(posts()).toHaveLength(0); expect(reading).not.toHaveBeenCalled();
    await act(async () => preflight.resolve(Response.json({ detail: "Unavailable" }, { status: 401 })));
    await settle(() => expect(button("Try again")).toBeDefined());
    expect(container.querySelector('[role="progressbar"]')).toBeNull();
    expect(posts()).toHaveLength(0); expect(reading).not.toHaveBeenCalled();
    expect(container.textContent).toContain("fictional-private-name.webp");
    readiness = async () => Response.json({ status: "ready" });
    await click(button("Try again"));
    expect(button("Read report").disabled).toBe(false);
    expect(consent().checked).toBe(true);
    expect(posts()).toHaveLength(0); expect(reading).not.toHaveBeenCalled();
  });
});
