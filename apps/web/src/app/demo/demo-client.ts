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
  constructor() { super("Your demo session expired. Send a new question or create a proposal to start again."); }
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

  private async call(path: string, body?: object): Promise<unknown> {
    let response: Response;
    try {
      response = await fetch(`/api/aquamind/v1/${path}`, {
        method: body ? "POST" : "GET", credentials: "omit",
        headers: { "Content-Type": "application/json", ...(this.#token ? { Authorization: `Bearer ${this.#token}` } : {}) },
        body: body ? JSON.stringify(body) : undefined, cache: "no-store",
        signal: AbortSignal.timeout(path === "agent/turn" || path === "agent/continue" ? 150_000 : 15_000),
      });
    } catch { throw new Error("The request could not be confirmed. It will not be retried automatically. Goals need your separate approval."); }
    if (response.status === 401) { this.#token = null; throw new SessionExpired(); }
    if (response.status === 429) throw new Error("The demo is busy or has reached its request limit. Please try later.");
    if (response.status === 409) throw new Error("A question is already being processed. Please wait before trying again.");
    if (!response.ok) throw new Error("The request could not be confirmed. Check the backend connection. Goals need your separate approval.");
    try { return await response.json(); } catch { throw invalid(); }
  }

  private async perform<T>(operation: () => Promise<T>): Promise<T> {
    if (this.#busy) throw new Error("Another request is still running. Please wait.");
    this.#busy = true;
    try {
      if (!this.#token) {
        const session = await this.call("sessions", {});
        if (!record(session) || typeof session.session_token !== "string" ||
            !/^[A-Za-z0-9_-]{40,128}$/.test(session.session_token)) throw invalid();
        this.#token = session.session_token;
      }
      return await operation();
    } finally { this.#busy = false; }
  }

  ask(text: string) {
    if (!text.trim() || new TextEncoder().encode(text).length > 8192) return Promise.reject(new Error("Enter a question of up to 8 KiB."));
    return this.perform(async () => parseAgentReply(await this.call("agent/turn", { text })));
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
