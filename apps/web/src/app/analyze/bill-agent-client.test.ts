import { afterEach, describe, expect, it, vi } from "vitest";
import { DemoClient, SessionExpired } from "../demo/demo-client";
import { createBillEntry, type BillDraft } from "../../lib/bills";

const draft: BillDraft = { period_start: "2026-06-01", period_end_exclusive: "2026-07-01", usage: "8.5",
  usage_unit: "ccf", water_charge: "45.12", sewer_charge: "", currency: "USD" };
const bill = () => createBillEntry(draft);
const token = "c".repeat(43);
const session = () => Response.json({ session_token: token });
const reply = { status: "answer", answer: "One bill is limited evidence.", pending_approval: null, tool_trace: [] };
afterEach(() => vi.unstubAllGlobals());

describe("explicit bill-only questions", () => {
  it("requires sharing consent and valid input before any session or provider request", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    await expect(new DemoClient().askBill("Explain it.", bill(), false, false)).rejects.toThrow("sharing");
    await expect(new DemoClient().askBill(" ", bill(), false, true)).rejects.toThrow("question");
    await expect(new DemoClient().askBill("é".repeat(4097), bill(), false, true)).rejects.toThrow("8 KiB");
    await expect(new DemoClient().askBill("Explain it.", { ...bill(), period_start: "bad date" }, false, true)).rejects.toThrow("dates");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("captures the exact bill and example flag without accepting client-computed values or demo context", async () => {
    let release!: (value: Response) => void;
    const fetcher = vi.fn().mockReturnValueOnce(new Promise<Response>((resolve) => { release = resolve; }))
      .mockResolvedValueOnce(Response.json(reply));
    vi.stubGlobal("fetch", fetcher);
    const entered = { ...bill(), total_us_gallons: "forged" };
    const pending = new DemoClient().askBill("Explain the average.", entered, true, true);
    entered.usage = "999";
    release(session());
    expect((await pending).answer).toBe(reply.answer);
    const [path, options] = fetcher.mock.calls[1];
    expect(path).toBe("/api/aquamind/v1/agent/bill");
    expect(options.headers.Authorization).toBe(`Bearer ${token}`);
    expect(options.credentials).toBe("omit");
    expect(options.cache).toBe("no-store");
    expect(JSON.parse(options.body)).toEqual({ text: "Explain the average.", bill: bill(), is_example: true, share_with_ai: true });
    expect(options.body).not.toContain("forged");
    expect(options.body).not.toContain("scenario_id");
    expect(options.body).not.toContain(token);
  });

  it("does not retry an uncertain paid answer or reflect raw provider errors", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockRejectedValueOnce(new Error("private backend detail"));
    vi.stubGlobal("fetch", fetcher);
    await expect(new DemoClient().askBill("Explain.", bill(), false, true)).rejects.toThrow("not be retried automatically");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("rejects pending proposals and successful tools in the read-only bill response", async () => {
    for (const unexpected of [
      { ...reply, tool_trace: [{ tool_name: "get_utility_rate", status: "success", elapsed_ms: 1 }] },
      { ...reply, status: "approval_required", answer: "", pending_approval: {
        approval_id: "12345678-abcd-1234-abcd-123456789abc", status: "approval_required",
        arguments: { daily_gallons: 150 }, summary: "Set a goal." } },
    ]) {
      const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json(unexpected));
      vi.stubGlobal("fetch", fetcher);
      await expect(new DemoClient().askBill("Explain.", bill(), false, true)).rejects.toThrow("invalid response");
      expect(fetcher).toHaveBeenCalledTimes(2);
    }
  });

  it("keeps normal bill calculation available after the optional assistant is unavailable", async () => {
    const normalized = { source: "manual_entry", evidence_level: "bill_only", confidence: "limited",
      request_id: "12345678-abcd-1234-abcd-123456789abc", bill: bill(), billing_days: 30,
      total_us_gallons: "6358.441558", us_gallons_per_day: "211.948052", water_and_sewer_subtotal: null };
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json({}, { status: 503 }))
      .mockResolvedValueOnce(Response.json(normalized));
    vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    await expect(client.askBill("Explain.", bill(), false, true)).rejects.toThrow("calculation is still available");
    expect((await client.normalizeBill(draft)).us_gallons_per_day).toBe("211.948052");
    expect(fetcher.mock.calls.filter(([path]) => path.endsWith("/sessions"))).toHaveLength(1);
  });

  it("drops an expired token and requires an explicit new bill question", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json({}, { status: 401 }))
      .mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json(reply));
    vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    await expect(client.askBill("First.", bill(), false, true)).rejects.toBeInstanceOf(SessionExpired);
    expect(fetcher).toHaveBeenCalledTimes(2);
    await client.askBill("New explicit question.", bill(), false, true);
    expect(fetcher.mock.calls[2][0]).toBe("/api/aquamind/v1/sessions");
    expect(fetcher.mock.calls[2][1].headers.Authorization).toBeUndefined();
  });
});
