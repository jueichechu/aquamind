import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "./route";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("deployment health", () => {
  it("fails closed without a backend address and makes no request", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "");
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const response = await GET();
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ status: "unavailable" });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("checks only backend liveness, with a deadline, no credentials and no cache", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "http://private-api:8000/");
    const fetcher = vi.fn().mockResolvedValue(Response.json({ status: "ok", private_metadata: "hidden" }));
    vi.stubGlobal("fetch", fetcher);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const response = await GET();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "ok" });
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(fetcher).toHaveBeenCalledExactlyOnceWith("http://private-api:8000/health", {
      cache: "no-store", redirect: "error", signal: expect.any(AbortSignal),
    });
    expect(timeout).toHaveBeenCalledWith(5_000);
  });

  it.each([
    () => Promise.resolve(Response.json({ status: "ok" }, { status: 503 })),
    () => Promise.resolve(Response.json({ status: "wrong" })),
    () => Promise.resolve(new Response("not json")),
    () => Promise.resolve(Response.json(null)),
    () => Promise.reject(new Error("private host or provider details")),
  ])("returns generic unavailability for upstream failure without retrying", async (reply) => {
    vi.stubEnv("AQUAMIND_API_URL", "http://private-api:8000");
    const fetcher = vi.fn().mockImplementation(reply);
    vi.stubGlobal("fetch", fetcher);
    const response = await GET();
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ status: "unavailable" });
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
