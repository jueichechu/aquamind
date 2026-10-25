import { afterEach, describe, expect, it, vi } from "vitest";
import { DemoClient, SessionExpired } from "../demo/demo-client";
import { createBillEntry, type BillDraft } from "../../lib/bills";

const draft: BillDraft = { period_start: "2026-06-01", period_end_exclusive: "2026-07-01", usage: "3000.000001",
  usage_unit: "us_gallons", water_charge: "45.12", sewer_charge: "", currency: "USD" };
const token = "b".repeat(43);
const session = () => Response.json({ session_token: token });
const result = () => ({ source: "manual_entry", evidence_level: "bill_only", confidence: "limited",
  request_id: "12345678-abcd-1234-abcd-123456789abc", bill: createBillEntry(draft), billing_days: 30,
  total_us_gallons: "3000.000001", us_gallons_per_day: "100.000000", water_and_sewer_subtotal: null });
afterEach(() => vi.unstubAllGlobals());

describe("bill normalization transport", () => {
  it("sends only structured bill fields to the same-origin endpoint with an in-memory bearer session", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json(result()));
    vi.stubGlobal("fetch", fetcher);
    const entry = await new DemoClient().normalizeBill(draft);
    expect(entry.total_us_gallons).toBe("3000.000001");
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(["/api/aquamind/v1/sessions", "/api/aquamind/v1/bills/normalize"]);
    const [url, options] = fetcher.mock.calls[1];
    expect(url).not.toContain(token);
    expect(options.headers.Authorization).toBe(`Bearer ${token}`);
    expect(options.credentials).toBe("omit");
    expect(options.cache).toBe("no-store");
    expect(JSON.parse(options.body)).toEqual(createBillEntry(draft));
    expect(JSON.parse(options.body).usage).toBe("3000.000001");
    expect(JSON.parse(options.body)).not.toHaveProperty("scenario_id");
  });

  it("rejects invalid entries before creating a session or sending private data", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    await expect(new DemoClient().normalizeBill({ ...draft, usage_unit: "gallons" })).rejects.toThrow("unit");
    await expect(new DemoClient().normalizeBill({ ...draft, currency: "" })).rejects.toThrow("USD");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("captures the bill before the session handshake and rejects overlapping requests", async () => {
    let release!: (response: Response) => void;
    const fetcher = vi.fn().mockReturnValueOnce(new Promise<Response>((resolve) => { release = resolve; }))
      .mockResolvedValueOnce(Response.json(result()));
    vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    const changing = { ...draft };
    const first = client.normalizeBill(changing);
    changing.usage = "999";
    await expect(client.normalizeBill(draft)).rejects.toThrow("still running");
    release(session());
    expect((await first).bill.usage).toBe("3000.000001");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("forgets an expired session and waits for explicit resubmission without replaying the bill", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json({}, { status: 401 }))
      .mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json(result()));
    vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    await expect(client.normalizeBill(draft)).rejects.toBeInstanceOf(SessionExpired);
    expect(fetcher).toHaveBeenCalledTimes(2);
    await client.normalizeBill(draft);
    expect(fetcher.mock.calls[2][0]).toBe("/api/aquamind/v1/sessions");
    expect(fetcher.mock.calls[2][1].headers.Authorization).toBeUndefined();
  });

  it("sanitizes validation and connection errors without automatic retries or model calls", async () => {
    for (const status of [422, 503]) {
      const fetcher = vi.fn().mockResolvedValueOnce(session())
        .mockResolvedValueOnce(Response.json({ detail: "private bill data" }, { status }));
      vi.stubGlobal("fetch", fetcher);
      await expect(new DemoClient().normalizeBill(draft)).rejects.toThrow(status === 422 ? "after conversion" : "unavailable");
      expect(fetcher).toHaveBeenCalledTimes(2);
    }
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockRejectedValueOnce(new Error("private bill data"));
    vi.stubGlobal("fetch", fetcher);
    await expect(new DemoClient().normalizeBill(draft)).rejects.toThrow("Check your connection");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("shows a bill-specific error when session creation cannot reach the backend", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json({ detail: "private backend detail" }, { status: 503 }));
    vi.stubGlobal("fetch", fetcher);
    await expect(new DemoClient().normalizeBill(draft)).rejects.toThrow("Bill analysis is unavailable");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("rejects a mismatched bill result without displaying another entry's values", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json({
      ...result(), bill: { ...result().bill, usage_unit: "liters" },
    }));
    vi.stubGlobal("fetch", fetcher);
    await expect(new DemoClient().normalizeBill(draft)).rejects.toThrow("invalid result");
  });
});
