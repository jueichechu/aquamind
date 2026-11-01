import { afterEach, describe, expect, it, vi } from "vitest";
import corpus from "../../../../../evals/fixtures/bill-comparison-contract-v1.json";
import { createBillComparisonEntries } from "../../lib/bill-comparison";
import { DemoClient, SessionExpired } from "../demo/demo-client";

const sample = corpus.cases[0];
const token = "b".repeat(43);
const session = () => Response.json({ session_token: token });
const result = () => Response.json(sample.response);
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("bill comparison transport", () => {
  it("sends only original entered fields with an in-memory bearer and the calculation timeout", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(result());
    vi.stubGlobal("fetch", fetcher);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const drafts = sample.drafts.map((bill) => ({ ...bill, account_number: "private-marker", share_with_ai: true }));
    const compared = await new DemoClient().compareBills(drafts);
    expect(compared.latest_percent_change).toBe("34.83");
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(["/api/aquamind/v1/sessions", "/api/aquamind/v1/bills/compare"]);
    const [url, options] = fetcher.mock.calls[1];
    expect(url).not.toContain(token);
    expect(options.headers.Authorization).toBe(`Bearer ${token}`);
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(options.credentials).toBe("omit");
    expect(options.cache).toBe("no-store");
    expect(JSON.parse(options.body)).toEqual({ bills: createBillComparisonEntries(sample.drafts) });
    expect(options.body).not.toContain("private-marker");
    expect(options.body).not.toContain("share_with_ai");
    expect(options.body).not.toContain("baseline");
    expect(timeout.mock.calls).toEqual([[15_000], [15_000]]);
  });

  it("rejects invalid bills, duplicates and counts before creating a session", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    for (const drafts of [[], sample.drafts.slice(0, 1), Array(13).fill(sample.drafts[0]),
      [sample.drafts[0], sample.drafts[0]],
      [sample.drafts[0], { ...sample.drafts[1], usage_unit: "gallons" }]]) {
      await expect(new DemoClient().compareBills(drafts)).rejects.toThrow();
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("captures every draft before session creation and shares the client concurrency guard", async () => {
    let release!: (response: Response) => void;
    const fetcher = vi.fn().mockReturnValueOnce(new Promise<Response>((resolve) => { release = resolve; }))
      .mockResolvedValueOnce(result());
    vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    const drafts = structuredClone(sample.drafts);
    const first = client.compareBills(drafts);
    drafts[1].usage = "999";
    drafts.reverse();
    drafts.pop();
    await expect(client.compareBills(sample.drafts)).rejects.toThrow("still running");
    await expect(client.normalizeBill(sample.drafts[0])).rejects.toThrow("still running");
    release(session());
    const compared = await first;
    expect(compared.bills[0].bill.usage).toBe("03100.00");
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ bills: createBillComparisonEntries(sample.drafts) });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("clears expired sessions and waits for explicit resubmission without replaying bills", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session())
      .mockResolvedValueOnce(Response.json({ detail: "private-marker" }, { status: 401 }))
      .mockResolvedValueOnce(session()).mockResolvedValueOnce(result());
    vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    await expect(client.compareBills(sample.drafts)).rejects.toBeInstanceOf(SessionExpired);
    expect(fetcher).toHaveBeenCalledTimes(2);
    await expect(client.compareBills(sample.drafts)).resolves.toMatchObject({ gap_days: 31 });
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "/api/aquamind/v1/sessions", "/api/aquamind/v1/bills/compare",
      "/api/aquamind/v1/sessions", "/api/aquamind/v1/bills/compare",
    ]);
  });

  it("reuses only its own session across explicit comparisons", async () => {
    const fetcher = vi.fn().mockImplementation(async (url) => url.endsWith("sessions") ? session() : result());
    vi.stubGlobal("fetch", fetcher);
    const first = new DemoClient();
    await first.compareBills(sample.drafts);
    await first.compareBills(sample.drafts);
    await new DemoClient().compareBills(sample.drafts);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith("sessions"))).toHaveLength(2);
    expect(fetcher).toHaveBeenCalledTimes(5);
  });

  it("sanitizes HTTP errors without echoing bill data or retrying", async () => {
    for (const [status, message] of [[422, "overlap"], [503, "Bill analysis is unavailable"],
      [429, "request limit"], [409, "already being processed"]] as const) {
      const fetcher = vi.fn().mockResolvedValueOnce(session())
        .mockResolvedValueOnce(Response.json({ detail: "private-marker" }, { status }));
      vi.stubGlobal("fetch", fetcher);
      await expect(new DemoClient().compareBills(sample.drafts)).rejects.toThrow(message);
      expect(fetcher).toHaveBeenCalledTimes(2);
    }
  });

  it("does not retry network failures and unlocks for the next explicit request", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockRejectedValueOnce(new Error("private-marker"))
      .mockResolvedValueOnce(result());
    vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    await expect(client.compareBills(sample.drafts)).rejects.toThrow("Check your connection");
    expect(fetcher).toHaveBeenCalledTimes(2);
    await expect(client.compareBills(sample.drafts)).resolves.toMatchObject({ baseline_bill_count: 2 });
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("rejects malformed sessions and invalid or mismatched result data", async () => {
    const noSession = vi.fn().mockResolvedValue(Response.json({ session_token: "bad" }));
    vi.stubGlobal("fetch", noSession);
    await expect(new DemoClient().compareBills(sample.drafts)).rejects.toThrow("invalid response");
    expect(noSession).toHaveBeenCalledTimes(1);
    for (const invalid of [Response.json({ ...sample.response, confidence: "verified" }),
      Response.json({ ...sample.response, baseline_bill_count: 3 }), new Response("not JSON")]) {
      const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(invalid);
      vi.stubGlobal("fetch", fetcher);
      await expect(new DemoClient().compareBills(sample.drafts)).rejects.toThrow(/invalid (comparison|response)/);
      expect(fetcher).toHaveBeenCalledTimes(2);
    }
  });
});
