import { afterEach, describe, expect, it, vi } from "vitest";
import { BILL_STARTUP_UNAVAILABLE, waitForBillReadiness } from "./bill-readiness";
import { GET } from "../app/api/aquamind/[...path]/route";

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.useRealTimers(); });

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

  it.each([429, 503])("honors a throttled or unavailable probe's Retry-After (%s)", async (status) => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json({}, { status, headers: { "Retry-After": "30" } }))
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

  it.each([401, 403, 404, 429, 503])("stops on configuration errors or an excessive cooldown (%s)", async (status) => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ detail: "private" }, {
      status, headers: { "Retry-After": "86400" },
    }));
    vi.stubGlobal("fetch", fetcher);
    await expect(waitForBillReadiness(new AbortController().signal)).rejects.toThrow(BILL_STARTUP_UNAVAILABLE);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("recovers through the relay from an edge error without sending a session or report", async () => {
    vi.useFakeTimers();
    vi.stubEnv("AQUAMIND_API_URL", "https://api.example");
    vi.stubEnv("AQUAMIND_RELAY_REQUIRED", "0");
    vi.stubEnv("AQUAMIND_PUBLIC_MODE", "0");
    const upstream = vi.fn().mockResolvedValueOnce(new Response("private edge page", {
      status: 429, headers: { "Content-Type": "text/html", "Retry-After": "30" },
    })).mockResolvedValueOnce(Response.json({ status: "ready" }));
    const fetcher = vi.fn().mockImplementation((url: string, options: RequestInit) => {
      if (url.startsWith("https://api.example/")) return upstream(url, options);
      return GET(new Request("https://website.example" + url, options), {
        params: Promise.resolve({ path: ["v1", "bills", "readiness"] }),
      });
    });
    vi.stubGlobal("fetch", fetcher);
    const wait = waitForBillReadiness(new AbortController().signal);
    await vi.advanceTimersByTimeAsync(29_999);
    expect(upstream).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await wait;
    expect(upstream).toHaveBeenCalledTimes(2);
    for (const [url, options] of fetcher.mock.calls) {
      expect(url).toContain("/bills/readiness");
      expect(options.method).toBe("GET");
      expect(options.body).toBeUndefined();
    }
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
