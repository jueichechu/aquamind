// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MeterWorkspace } from "./meter-workspace";
import { MeterClient } from "../../lib/meter-import";

const token = "s".repeat(43);
const result = () => ({ context: { evidence_id: "meter_example", household_id: "house_example", origin: "user_provided",
  dataset_sha256: "a".repeat(64), start: "2026-06-01T00:00:00Z", end_exclusive: "2026-06-01T00:15:00Z", reading_count: 1,
  interval_minutes: 15, volume_unit: "us_gallons", reading_type: "actual" }, timezone: "UTC", total_us_gallons: "15.000000",
  inference_status: "not_enabled_for_imported_data", limitations: ["Unverified user-provided readings."] });
let root: Root, host: HTMLDivElement;
let calls: { path: string; init: RequestInit }[];
let importing: () => Promise<Response>;
let reading: () => Promise<Response>;
let answering: () => Promise<Response>;
function element<T extends HTMLElement>(id: string) { return host.querySelector<T>(`#${id}`)!; }
function button(text: string) { return [...host.querySelectorAll("button")].find((item) => item.textContent === text)!; }
async function click(target: HTMLElement) { await act(async () => target.click()); }
async function change(id: string, value: string) {
  const field = element<HTMLInputElement | HTMLSelectElement>(id);
  await act(async () => {
    const prototype = field instanceof HTMLSelectElement ? HTMLSelectElement.prototype : field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("change", { bubbles: true })); field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function choose() {
  const input = element<HTMLInputElement>("meter-file");
  const file = new File(["interval_start,volume\n2026-06-01T00:00:00Z,15\n"], "readings.csv");
  Object.defineProperty(file, "arrayBuffer", { value: async () => new TextEncoder().encode("interval_start,volume\n2026-06-01T00:00:00Z,15\n").buffer });
  Object.defineProperty(input, "files", { configurable: true, value: [file] });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
}
async function prepare() {
  await choose(); await change("meter-unit", "us_gallons"); await change("meter-timezone", "UTC");
  await change("meter-reading", "actual"); await click(element("meter-consent"));
}
async function submit() {
  await act(async () => host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
}
beforeEach(async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host); calls = [];
  importing = async () => Response.json(result());
  reading = async () => Response.json(result());
  answering = async () => Response.json({status:'answer',answer:'The meter covers only part of the unverified bill, so the totals cannot be compared.',pending_approval:null,
    tool_trace:[{tool_name:'get_meter_summary',status:'success',elapsed_ms:1}]});
  vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit) => {
    calls.push({ path, init });
    if (path.endsWith('/bills/readiness')) return Response.json({status:'ready'});
    if (path.endsWith('/agent/evidence')) return answering();
    if (path.endsWith("/sessions")) return Response.json({ session_token: token });
    if (path.endsWith("/import")) return importing();
    if (init.method === "DELETE") return new Response(null, { status: 204 });
    return reading();
  }));
  await act(async () => root.render(<MeterWorkspace />));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("keeps selection local until consent, focuses real results, resets review and clears", async () => {
  await choose(); expect(calls).toHaveLength(0);
  await submit(); expect(calls).toHaveLength(0);
  await prepare(); await submit();
  expect(calls.filter((item) => item.path.endsWith("/import"))).toHaveLength(1);
  expect(document.activeElement).toBe(element("meter-result-heading"));
  expect(host.textContent).toContain("Total US gallons15");
  expect((element<HTMLInputElement>("meter-reviewed")).checked).toBe(false);
  await click(element("meter-reviewed")); expect(host.textContent).toContain("Reviewed by you; the readings remain unverified.");
  await choose(); expect(element<HTMLInputElement>("meter-reviewed").checked).toBe(false);
  expect(element<HTMLInputElement>("meter-reviewed").disabled).toBe(true);
  expect(element<HTMLInputElement>("meter-consent").checked).toBe(false);
  await click(button("Remove pending file")); await click(button("Clear selected readings"));
  expect(host.textContent).toContain("No readings selected.");
  expect(document.activeElement).toBe(element("meter-file"));
  expect(calls.filter((item) => item.init.method === "DELETE")).toHaveLength(1);
  expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0);
});

it("shows loading, blocks duplicate writes and removes consent after completion", async () => {
  let finish!: (value: Response) => void;
  importing = () => new Promise<Response>((yes) => { finish = yes; });
  await prepare(); await submit();
  expect(host.textContent).toContain("Validating timestamps");
  expect(button("Importing readings…").disabled).toBe(true);
  await submit(); expect(calls.filter((item) => item.path.endsWith("/import"))).toHaveLength(1);
  await act(async () => finish(Response.json(result())));
  expect(element<HTMLInputElement>("meter-consent").checked).toBe(false);
});

it("keeps a confirmed selection after a rejected replacement and sanitizes errors", async () => {
  await prepare(); await submit();
  importing = async () => new Response("PRIVATE_CSV_CONTENT", { status: 422 });
  await prepare(); await submit();
  expect(host.textContent).toContain("Total US gallons15");
  expect(host.textContent).not.toContain("PRIVATE_CSV_CONTENT");
  expect(document.activeElement?.getAttribute("role")).toBe("alert");
  expect(element<HTMLInputElement>("meter-reviewed").checked).toBe(false);
});

it("hides stale data on uncertain writes and recovers through explicit read-back only", async () => {
  await prepare(); await submit();
  importing = async () => { throw new TypeError("connection interrupted"); };
  await prepare(); await submit();
  expect(host.textContent).toContain("current selection is unconfirmed");
  expect(host.textContent).not.toContain("Total US gallons15");
  expect(calls.filter((item) => item.path.endsWith("/import"))).toHaveLength(2);
  reading = async () => new Response(null, { status: 429 });
  await click(button("Check current selection"));
  expect(host.textContent).toContain("current selection is unconfirmed");
  expect(button("Import CSV").disabled).toBe(true);
  reading = async () => Response.json(result());
  await click(button("Check current selection"));
  expect(host.textContent).toContain("Total US gallons15");
  expect(calls.filter((item) => item.path.endsWith("/import"))).toHaveLength(2);
  expect(calls.filter((item) => item.init.method === "GET")).toHaveLength(2);
});

it("handles disabled deployments and expired sessions without automatic replay", async () => {
  importing = async () => new Response(null, { status: 404 });
  await prepare(); await submit(); expect(host.textContent).toContain("not enabled on this deployment");
  expect(host.querySelector('a[href="/analyze"]')).not.toBeNull();
  importing = async () => new Response(null, { status: 401 });
  await prepare(); await submit(); expect(host.textContent).toContain("meter session ended");
  expect(calls.filter((item) => item.path.endsWith("/sessions"))).toHaveLength(1);
  expect(element<HTMLInputElement>("meter-consent").checked).toBe(false);
});

it("clears local evidence and attempts session revocation when the page is left", async () => {
  await prepare(); await submit(); await click(element("meter-reviewed"));
  await act(async () => window.dispatchEvent(new Event("pagehide")));
  expect(host.textContent).toContain("No readings selected.");
  expect(host.querySelector("#meter-reviewed")).toBeNull();
  expect(element<HTMLInputElement>("meter-consent").checked).toBe(false);
  const close = calls.filter((item) => item.path.endsWith("/session"));
  expect(close).toHaveLength(1); expect(close[0].init.keepalive).toBe(true);
});

async function evidenceForm() {
  await prepare(); await submit(); await click(element('meter-reviewed'));
  for (const [suffix,value] of Object.entries({start:'2026-06-01',end:'2026-07-01',usage:'810',unit:'us_gallons'})) {
    await change(`evidence-bill-${suffix}`,value);
  }
  await change('evidence-timezone','UTC');
  await change('evidence-question','What does this household bill and meter coverage tell me?');
  await click(element('evidence-reviewed')); await click(element('evidence-household'));
}
async function submitEvidence() { await click(button('Ask with bill and meter')); }

it('requires source review, household assertion and separate AI consent, then resets sharing on edits', async()=>{
  await evidenceForm();
  expect(button('Ask with bill and meter').disabled).toBe(true);
  expect(calls.filter(c=>c.path.endsWith('/agent/evidence'))).toHaveLength(0);
  await click(element('evidence-sharing-consent')); await submitEvidence();
  const question=calls.find(c=>c.path.endsWith('/agent/evidence'))!;
  const body=JSON.parse(question.init.body as string);
  expect(body).toMatchObject({meter_evidence_id:'meter_example',bill_reviewed:true,meter_reviewed:true,same_household:true,share_with_ai:true,bill_input_method:'manual_entry'});
  expect(body).not.toHaveProperty('household_id'); expect(body).not.toHaveProperty('csv_text');
  expect(host.textContent).toContain('totals cannot be compared');
  expect(document.activeElement?.textContent).toBe('Bill and meter answer');
  expect(element<HTMLInputElement>('evidence-sharing-consent').checked).toBe(false);
  await change('evidence-bill-usage','820');
  expect(host.querySelector('article[aria-label="Bill-and-meter answer"]')).toBeNull();
  expect(element<HTMLInputElement>('evidence-reviewed').checked).toBe(false);
  expect(element<HTMLInputElement>('evidence-household').checked).toBe(false);
});

it('locks meter mutation during a question and never double-submits a paid request', async()=>{
  let finish!:(value:Response)=>void;
  answering=()=>new Promise(resolve=>{finish=resolve;});
  await evidenceForm();await click(element('evidence-sharing-consent'));await submitEvidence();
  expect(button('Comparing the evidence…').disabled).toBe(true);
  expect(button('Clear selected readings').disabled).toBe(true);
  expect(element<HTMLInputElement>('meter-reviewed').disabled).toBe(true);
  expect(host.textContent).toContain('No automatic retries');
  await act(async()=>finish(Response.json({status:'unavailable',answer:'',pending_approval:null,tool_trace:[]})));
  expect(calls.filter(c=>c.path.endsWith('/agent/evidence'))).toHaveLength(1);
  expect(element<HTMLTextAreaElement>('evidence-question').value).not.toBe('');
  expect(element<HTMLInputElement>('evidence-sharing-consent').checked).toBe(false);
  expect(button('Clear selected readings').disabled).toBe(false);
});

it('keeps the meter selection on incompatible bills and requires read-back after stale references', async()=>{
  await evidenceForm();
  answering=async()=>new Response('PRIVATE_BILL_TEXT',{status:422});
  await click(element('evidence-sharing-consent'));await submitEvidence();
  expect(host.textContent).toContain('inside the bill period');
  expect(host.textContent).not.toContain('PRIVATE_BILL_TEXT');
  expect(host.textContent).toContain('Total US gallons15');
  answering=async()=>new Response(null,{status:409});
  await click(element('evidence-sharing-consent'));await submitEvidence();
  expect(host.textContent).toContain('Check the current meter selection');
  expect(host.querySelector('#evidence-heading')).toBeNull();
  await click(button('Check current selection'));
  expect(element<HTMLInputElement>('meter-reviewed').checked).toBe(false);
});

it('preserves the question after network failure without replaying and drops answers after meter edits', async()=>{
  await evidenceForm();
  answering=async()=>{throw new TypeError('network lost');};
  await click(element('evidence-sharing-consent'));await submitEvidence();
  expect(host.textContent).toContain('not be retried automatically');
  expect(calls.filter(c=>c.path.endsWith('/agent/evidence'))).toHaveLength(1);
  expect(element<HTMLInputElement>('evidence-sharing-consent').checked).toBe(false);
  await choose(); expect(host.querySelector('#evidence-heading')).toBeNull();
});

it('supports document candidates without treating extraction or user edits as verified evidence', async()=>{
  await evidenceForm();
  expect(host.querySelector('a[href="#evidence-bill-start"]')?.textContent).toBe('Enter details instead');
  const imported={draft:{period_start:'2026-06-01',period_end_exclusive:'2026-07-01',usage:'810',usage_unit:'us_gallons',water_charge:'',sewer_charge:'',currency:''},warnings:[]};
  vi.spyOn(MeterClient.prototype,'importBill').mockResolvedValue(imported);
  const input=host.querySelector<HTMLInputElement>('input[aria-label="Choose a water bill report"]')!;
  await act(async()=>{
    Object.defineProperty(input,'files',{configurable:true,value:[new File(['fictional'],'bill.webp',{type:'image/webp'})]});
    input.dispatchEvent(new Event('change',{bubbles:true}));
  });
  const sharing=host.querySelector<HTMLInputElement>('input[aria-describedby="report-sharing"]')!;
  await click(sharing); await click(button('Read report'));
  expect(element<HTMLInputElement>('evidence-bill-usage').value).toBe('810');
  expect(element<HTMLInputElement>('evidence-reviewed').checked).toBe(false);
  expect(element<HTMLInputElement>('evidence-sharing-consent').checked).toBe(false);
  expect(host.textContent).toContain('editable candidates');
});
