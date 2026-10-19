import { afterEach, describe, expect, it, vi } from "vitest";
import { DemoClient, parseAgentReply, SessionExpired, type Proposal } from "./demo-client";

const token = "a".repeat(43);
const id = "12345678-abcd-1234-abcd-123456789abc";
const proposal: Proposal = { approval_id: id, status: "approval_required",
  arguments: { daily_gallons: 150 }, summary: "Set your goal to 150 gallons/day." };
const reply = { status: "answer", answer: "Illustrative cost: $5.00.", pending_approval: null,
  tool_trace: [{ tool_name: "estimate_water_cost", status: "success", elapsed_ms: 5 }] };
const session = () => Response.json({ session_token: token });
afterEach(() => { vi.unstubAllGlobals(); });

describe("shared in-memory demo client", () => {
  it("uses one session for chat, manual goals, review and explicit decisions", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json(reply))
      .mockResolvedValueOnce(Response.json(proposal)).mockResolvedValueOnce(Response.json(proposal))
      .mockResolvedValueOnce(Response.json({ ...proposal, status: "approved" }));
    vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    expect((await client.ask("Estimate 1,000 gallons.")).status).toBe("answer");
    const pending = await client.propose(150);
    await client.review(pending);
    expect((await client.decide(pending, "approve")).status).toBe("approved");
    expect(fetcher.mock.calls.map(([path]) => path)).toEqual([
      "/api/aquamind/v1/sessions", "/api/aquamind/v1/agent/turn", "/api/aquamind/v1/goals/proposals",
      `/api/aquamind/v1/approvals/${id}`, `/api/aquamind/v1/approvals/${id}/decision`,
    ]);
    for (const [path, options] of fetcher.mock.calls) {
      expect(path).not.toContain(token);
      expect(options.body ?? "").not.toContain(token);
      expect(options.credentials).toBe("omit");
      if (!path.endsWith("/sessions")) expect(options.headers.Authorization).toBe(`Bearer ${token}`);
    }
    expect(fetcher.mock.calls[4][1].body).toBe('{"decision":"approve"}');
  });

  it("delivers an agent proposal without making any decision request", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json({
      ...reply, status: "approval_required", answer: "", pending_approval: proposal,
    }));
    vi.stubGlobal("fetch", fetcher);
    const result = await new DemoClient().ask("Propose a daily goal of 150 gallons.");
    expect(result.pending_approval).toEqual(proposal);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls.some(([path]) => path.includes("/decision"))).toBe(false);
  });

  it("retains the session and permits an explicit safe decision retry after failure", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json(proposal))
      .mockRejectedValueOnce(new Error("secret provider detail"))
      .mockResolvedValueOnce(Response.json({ ...proposal, status: "approved" }));
    vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    await client.propose(150);
    await expect(client.decide(proposal, "approve")).rejects.toThrow("could not be confirmed");
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect((await client.decide(proposal, "approve")).status).toBe("approved");
    expect(fetcher.mock.calls[2][0]).toBe(fetcher.mock.calls[3][0]);
    expect(fetcher.mock.calls[3][1].headers.Authorization).toBe(`Bearer ${token}`);
  });

  it("forgets an expired session and never automatically retries a paid question", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json({}, { status: 401 }))
      .mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json(reply));
    vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    await expect(client.ask("First question")).rejects.toBeInstanceOf(SessionExpired);
    expect(fetcher).toHaveBeenCalledTimes(2);
    await client.ask("A new question");
    expect(fetcher.mock.calls[2][0]).toBe("/api/aquamind/v1/sessions");
    expect(fetcher.mock.calls[2][1].headers.Authorization).toBeUndefined();
  });

  it("rejects concurrent requests before starting a second session or model call", async () => {
    let release!: (value: Response) => void;
    const fetcher = vi.fn().mockReturnValueOnce(new Promise<Response>((resolve) => { release = resolve; }))
      .mockResolvedValueOnce(Response.json(reply));
    vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    const first = client.ask("First question");
    await expect(client.ask("Duplicate")).rejects.toThrow("still running");
    expect(fetcher).toHaveBeenCalledTimes(1);
    release(session());
    await first;
  });

  it("rejects invalid input and inconsistent server results without reflecting secrets", async () => {
    const client = new DemoClient();
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json({
      ...proposal, approval_id: "87654321-abcd-1234-abcd-123456789abc", status: "approved",
    }));
    vi.stubGlobal("fetch", fetcher);
    await expect(client.ask("é".repeat(4097))).rejects.toThrow("8 KiB");
    await expect(client.propose(Infinity)).rejects.toThrow("daily goal");
    expect(fetcher).not.toHaveBeenCalled();
    await expect(client.decide(proposal, "approve")).rejects.toThrow("invalid response");
    for (const invalid of [
      { ...reply, pending_approval: proposal },
      { ...reply, status: "approval_required", pending_approval: proposal },
      { ...reply, status: "approval_required", answer: "", pending_approval: { ...proposal, status: "approved" } },
      { ...reply, tool_trace: [{ tool_name: "secret", status: "success", elapsed_ms: -1 }] },
    ]) expect(() => parseAgentReply(invalid)).toThrow("invalid response");
  });

  it("surfaces busy/unavailable responses and never leaks backend details or retries", async () => {
    for (const status of [429, 503]) {
      const fetcher = vi.fn().mockResolvedValueOnce(session())
        .mockResolvedValueOnce(Response.json({ detail: "private backend detail" }, { status }));
      vi.stubGlobal("fetch", fetcher);
      await expect(new DemoClient().ask("Question")).rejects.not.toThrow("private backend detail");
      expect(fetcher).toHaveBeenCalledTimes(2);
    }
  });

  it("continues with only the proposal ID after a separately confirmed decision", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json({
      ...reply, status: "approval_required", answer: "", pending_approval: proposal,
    })).mockResolvedValueOnce(Response.json({ ...proposal, status: "approved" }))
      .mockResolvedValueOnce(Response.json({ ...reply, answer: "Your temporary goal is 150 gallons/day." }));
    vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    await client.ask("Propose 150 gallons/day.");
    const decision = await client.decide(proposal, "approve");
    expect(decision.status).toBe("approved");
    expect((await client.continueAfterDecision(id)).answer).toContain("150");
    expect(fetcher.mock.calls[3][0]).toBe("/api/aquamind/v1/agent/continue");
    expect(JSON.parse(fetcher.mock.calls[3][1].body)).toEqual({ approval_id: id });
    expect(fetcher.mock.calls[3][1].headers.Authorization).toBe(`Bearer ${token}`);
    expect(fetcher.mock.calls.filter(([path]) => path.endsWith("/decision"))).toHaveLength(1);
  });

  it("does not repeat a decision when an unconfirmed follow-up is explicitly checked", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json(proposal))
      .mockResolvedValueOnce(Response.json({ ...proposal, status: "approved" }))
      .mockRejectedValueOnce(new Error("private connection detail"))
      .mockResolvedValueOnce(Response.json(reply));
    vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    await client.propose(150);
    const confirmed = await client.decide(proposal, "approve");
    await expect(client.continueAfterDecision(id)).rejects.toThrow("could not be confirmed");
    expect(confirmed.status).toBe("approved");
    expect(fetcher).toHaveBeenCalledTimes(4);
    await client.continueAfterDecision(id);
    expect(fetcher.mock.calls[4][0]).toBe("/api/aquamind/v1/agent/continue");
    expect(fetcher.mock.calls.filter(([path]) => path.endsWith("/decision"))).toHaveLength(1);
  });

  it("rejects a new pending proposal in a read-only continuation", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json({
      ...reply, status: "approval_required", answer: "", pending_approval: proposal,
    }));
    vi.stubGlobal("fetch", fetcher);
    await expect(new DemoClient().continueAfterDecision(id)).rejects.toThrow("invalid response");
  });
});
