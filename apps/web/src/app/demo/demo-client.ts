import { SCENARIOS } from "../../lib/water/scenarios";
import type { ScenarioId } from "../../lib/water/types";
import { createBillEntry, parseBillResult, type BillDraft, type ManualBill } from "../../lib/bills";
import { checkReportSize, encodeReport, parseImportedBill } from "../../lib/bill-import";

export type Proposal = {
  approval_id: string;
  status: "approval_required" | "approved" | "rejected" | "expired" | "conflict";
  arguments: { daily_gallons: number };
  summary: string;
};
export type ToolEvent = { tool_name: string; status: string; elapsed_ms: number };
export type AgentReply = {
  status: "answer" | "approval_required" | "refused" | "limit_reached" | "unavailable" | "unconfirmed";
  answer: string;
  pending_approval: Proposal | null;
  tool_trace: ToolEvent[];
};

export class SessionExpired extends Error {
  constructor() { super("Your session expired. Submit a new request to start again."); }
}
const invalid = () => new Error("The server returned an invalid response. No action is confirmed.");
const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null;
const proposalStatuses = ["approval_required", "approved", "rejected", "expired", "conflict"];

export function parseProposal(value: unknown): Proposal {
  if (!record(value) || typeof value.approval_id !== "string" ||
      !/^[0-9a-f-]{36}$/.test(value.approval_id) || !proposalStatuses.includes(String(value.status)) ||
      typeof value.summary !== "string" || value.summary.length > 1024 || !record(value.arguments) ||
      typeof value.arguments.daily_gallons !== "number" || !Number.isFinite(value.arguments.daily_gallons) ||
      value.arguments.daily_gallons <= 0 || value.arguments.daily_gallons > 10000) throw invalid();
  return { approval_id: value.approval_id, status: value.status as Proposal["status"],
    summary: value.summary, arguments: { daily_gallons: value.arguments.daily_gallons } };
}

export function parseAgentReply(value: unknown): AgentReply {
  const statuses = ["answer", "approval_required", "refused", "limit_reached", "unavailable", "unconfirmed"];
  if (!record(value) || !statuses.includes(String(value.status)) || typeof value.answer !== "string" ||
      value.answer.length > 65536 || !Array.isArray(value.tool_trace) || value.tool_trace.length > 36) throw invalid();
  const pending = value.pending_approval === null ? null : parseProposal(value.pending_approval);
  if ((value.status === "approval_required") !== (pending !== null) ||
      (pending && (pending.status !== "approval_required" || value.answer !== "")) ||
      (value.status === "answer" && !value.answer.trim())) throw invalid();
  const trace = value.tool_trace.map((item: unknown) => {
    if (!record(item) || typeof item.tool_name !== "string" || item.tool_name.length > 80 ||
        typeof item.status !== "string" || item.status.length > 40 ||
        typeof item.elapsed_ms !== "number" || !Number.isFinite(item.elapsed_ms) || item.elapsed_ms < 0) throw invalid();
    return { tool_name: item.tool_name, status: item.status, elapsed_ms: item.elapsed_ms };
  });
  return { status: value.status as AgentReply["status"], answer: value.answer,
    pending_approval: pending, tool_trace: trace };
}

/** One instance per mounted panel. No cookies, browser storage, credentials in URLs, or automatic retries. */
export class DemoClient {
  #token: string | null = null;
  #busy = false;

  private async call(path: string, body?: object, forBill = false): Promise<unknown> {
    const importing = path === "bills/import";
    const billQuestion = path === "agent/bill";
    const bill = forBill || path === "bills/normalize" || billQuestion || importing;
    let response: Response;
    try {
      response = await fetch(`/api/aquamind/v1/${path}`, {
        method: body ? "POST" : "GET", credentials: "omit",
        headers: { "Content-Type": "application/json", ...(this.#token ? { Authorization: `Bearer ${this.#token}` } : {}) },
        body: body ? JSON.stringify(body) : undefined, cache: "no-store",
        signal: AbortSignal.timeout(path === "agent/turn" || path === "agent/continue" || billQuestion || importing ? 150_000 : 15_000),
      });
    } catch { throw new Error(importing ? "Report extraction could not be confirmed. It will not be retried automatically; another attempt may incur another charge." : billQuestion ? "Your bill question could not be confirmed. It will not be retried automatically." : bill ? "Your bill result could not be confirmed. Check your connection and submit again." :
      "The request could not be confirmed. It will not be retried automatically. Goals need your separate approval."); }
    if (response.status === 401) { this.#token = null; throw new SessionExpired(); }
    if (response.status === 429) throw new Error("The demo is busy or has reached its request limit. Please try later.");
    if (response.status === 409) throw new Error("A question is already being processed. Please wait before trying again.");
    if (importing && response.status === 413) throw new Error("Choose a report of up to 4 MiB.");
    if (importing && response.status === 422) throw new Error("Check the report format and confirm sharing with OpenAI.");
    if (importing && !response.ok) throw new Error("Report extraction is unavailable or could not be confirmed. There is no automatic retry; you can still enter your bill manually.");
    if (billQuestion && response.status === 422) throw new Error("Check your question and bill fields, and confirm sharing with OpenAI.");
    if (billQuestion && !response.ok) throw new Error("The bill assistant is unavailable. Your bill calculation is still available.");
    if (bill && response.status === 422) throw new Error("Check the billing dates, usage, units and charges. Usage must not exceed 1,000,000 US gallons after conversion.");
    if (bill && !response.ok) throw new Error("Bill analysis is unavailable. Please try again later.");
    if (!response.ok) throw new Error("The request could not be confirmed. Check the backend connection. Goals need your separate approval.");
    try { return await response.json(); } catch { throw invalid(); }
  }

  private async perform<T>(operation: () => Promise<T>, forBill = false): Promise<T> {
    if (this.#busy) throw new Error("Another request is still running. Please wait.");
    this.#busy = true;
    try {
      if (!this.#token) {
        const session = await this.call("sessions", {}, forBill);
        if (!record(session) || typeof session.session_token !== "string" ||
            !/^[A-Za-z0-9_-]{40,128}$/.test(session.session_token)) throw invalid();
        this.#token = session.session_token;
      }
      return await operation();
    } finally { this.#busy = false; }
  }

  ask(text: string, scenarioId?: ScenarioId) {
    if (!text.trim() || new TextEncoder().encode(text).length > 8192) return Promise.reject(new Error("Enter a question of up to 8 KiB."));
    if (scenarioId !== undefined && (typeof scenarioId !== "string" || !Object.hasOwn(SCENARIOS, scenarioId))) {
      return Promise.reject(new Error("Select a supported demo scenario."));
    }
    return this.perform(async () => parseAgentReply(await this.call("agent/turn", {
      text, ...(scenarioId === undefined ? {} : { scenario_id: scenarioId }),
    })));
  }
  normalizeBill(draft: BillDraft) {
    let entry: ManualBill;
    try { entry = createBillEntry(draft); }
    catch (cause) { return Promise.reject(cause); }
    return this.perform(async () => parseBillResult(await this.call("bills/normalize", entry), entry), true);
  }
  importBill(file: File, shareWithAI: boolean) {
    if (shareWithAI !== true) return Promise.reject(new Error("Confirm sharing this report with OpenAI first."));
    try { checkReportSize(file); } catch (cause) { return Promise.reject(cause); }
    return this.perform(async () => {
      const body = await encodeReport(file);
      return parseImportedBill(await this.call("bills/import", body));
    }, true);
  }
  askBill(text: string, bill: ManualBill, isExample: boolean, shareWithAI: boolean) {
    if (shareWithAI !== true) return Promise.reject(new Error("Confirm sharing this bill and question with OpenAI first."));
    if (!text.trim() || new TextEncoder().encode(text).length > 8192) return Promise.reject(new Error("Enter a question of up to 8 KiB."));
    if (typeof isExample !== "boolean") return Promise.reject(invalid());
    let entry: ManualBill;
    try { entry = createBillEntry({ ...bill, water_charge: bill.water_charge ?? "",
      sewer_charge: bill.sewer_charge ?? "", currency: bill.currency ?? "" }); }
    catch (cause) { return Promise.reject(cause); }
    return this.perform(async () => {
      const reply = parseAgentReply(await this.call("agent/bill", { text, bill: entry,
        is_example: isExample, share_with_ai: true }));
      if (reply.pending_approval !== null || reply.tool_trace.some((item) => item.status === "success")) throw invalid();
      return reply;
    }, true);
  }
  propose(daily_gallons: number) {
    if (!Number.isFinite(daily_gallons) || daily_gallons <= 0 || daily_gallons > 10000) return Promise.reject(new Error("Enter a daily goal between 0 and 10,000 gallons."));
    return this.perform(async () => parseProposal(await this.call("goals/proposals", { daily_gallons })));
  }
  continueAfterDecision(approval_id: string) {
    if (!/^[0-9a-f-]{36}$/.test(approval_id)) return Promise.reject(invalid());
    return this.perform(async () => {
      const reply = parseAgentReply(await this.call("agent/continue", { approval_id }));
      if (reply.pending_approval !== null) throw invalid();
      return reply;
    });
  }
  decide(proposal: Proposal, decision: "approve" | "reject") {
    return this.perform(async () => {
      const result = parseProposal(await this.call(`approvals/${proposal.approval_id}/decision`, { decision }));
      if (result.approval_id !== proposal.approval_id ||
          result.arguments.daily_gallons !== proposal.arguments.daily_gallons) throw invalid();
      return result;
    });
  }
  review(proposal: Proposal) {
    return this.perform(async () => {
      const result = parseProposal(await this.call(`approvals/${proposal.approval_id}`));
      if (result.approval_id !== proposal.approval_id ||
          result.arguments.daily_gallons !== proposal.arguments.daily_gallons) throw invalid();
      return result;
    });
  }
}
