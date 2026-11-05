import { afterEach, describe, expect, it, vi } from "vitest";
import { BILL_STARTUP_UNAVAILABLE, waitForBillReadiness } from "./bill-readiness";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("bill startup readiness", () => {
  it("waits through a cold start using only credential-free GETs, then stops", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json({}, { status: 503 }))
      .mockResolvedValueOnce(Response.json({ status: "ready" }));
    vi.stubGlobal("fetch", fetcher);
    const wait = waitForBillReadiness(new AbortController().signal);
    await vi.advanceTimersByTimeAsync(9_999);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await wait;
    await vi.advanceTimersByTimeAsync(180_000);
    expect(fetcher).toHaveBeenCalledTimes(2);
    for (const [url, options] of fetcher.mock.calls) {
      expect(url).toBe("/api/aquamind/v1/bills/readiness");
      expect(options).toMatchObject({ method: "GET", credentials: "omit", cache: "no-store" });
      expect(options.body).toBeUndefined();
      expect(options.headers).toBeUndefined();
    }
  });

  it("honors a throttled probe's Retry-After instead of hammering the service", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json({}, { status: 429, headers: { "Retry-After": "30" } }))
      .mockResolvedValueOnce(Response.json({ status: "ready" }));
    vi.stubGlobal("fetch", fetcher);
    const wait = waitForBillReadiness(new AbortController().signal);
    await vi.advanceTimersByTimeAsync(29_999);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await wait;
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("bounds repeated failures and never keeps an idle service awake indefinitely", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockImplementation(async () => Response.json({}, { status: 503 }));
    vi.stubGlobal("fetch", fetcher);
    const failure = expect(waitForBillReadiness(new AbortController().signal)).rejects.toThrow(BILL_STARTUP_UNAVAILABLE);
    await vi.advanceTimersByTimeAsync(120_000);
    await failure;
    const calls = fetcher.mock.calls.length;
    expect(calls).toBeLessThanOrEqual(12);
    await vi.advanceTimersByTimeAsync(180_000);
    expect(fetcher).toHaveBeenCalledTimes(calls);
  });

  it.each([401, 403, 404, 429])("stops on configuration errors or an excessive cooldown (%s)", async (status) => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ detail: "private" }, {
      status, headers: { "Retry-After": "86400" },
    }));
    vi.stubGlobal("fetch", fetcher);
    await expect(waitForBillReadiness(new AbortController().signal)).rejects.toThrow(BILL_STARTUP_UNAVAILABLE);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("does not accept generic liveness, malformed responses or network failures as readiness", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json({ status: "ok" }))
      .mockResolvedValueOnce(new Response("not json")).mockRejectedValueOnce(new Error("private network details"))
      .mockResolvedValueOnce(Response.json({ status: "ready" }));
    vi.stubGlobal("fetch", fetcher);
    const wait = waitForBillReadiness(new AbortController().signal);
    await vi.advanceTimersByTimeAsync(30_000);
    await wait;
    expect(fetcher).toHaveBeenCalledTimes(4);
  });

  it("cancels an in-flight probe and a pending poll on navigation", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const fetcher = vi.fn().mockImplementation((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(options.signal.reason), { once: true });
    }));
    vi.stubGlobal("fetch", fetcher);
    const cancelled = expect(waitForBillReadiness(controller.signal)).rejects.toThrow();
    controller.abort();
    await cancelled;
    fetcher.mockImplementation(async () => Response.json({}, { status: 503 }));
    const next = new AbortController();
    const paused = expect(waitForBillReadiness(next.signal)).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(0);
    next.abort();
    await paused;
    await vi.advanceTimersByTimeAsync(120_000);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
