import { afterEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "./route";
const context = (path: string) => ({ params: Promise.resolve({ path: path.split("/") }) });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });
describe("approval relay", () => {
  it("relays bill questions with a model deadline, bounded body and no browser cookies", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000");
    const fetcher = vi.fn().mockResolvedValue(Response.json({ status: "answer" }));
    vi.stubGlobal("fetch", fetcher);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const body = JSON.stringify({ text: "q".repeat(2000), bill: { usage: "8.5" }, is_example: true, share_with_ai: true });
    expect((await POST(new Request("http://localhost/api", { method: "POST", body,
      headers: { authorization: "Bearer test-session", cookie: "private=value" } }), context("v1/agent/bill"))).status).toBe(200);
    expect(fetcher.mock.calls[0][0]).toBe("http://localhost:8000/v1/agent/bill");
    expect(fetcher.mock.calls[0][1].body).toBe(body);
    expect(fetcher.mock.calls[0][1].headers.has("cookie")).toBe(false);
    expect(fetcher.mock.calls[0][1].headers.get("authorization")).toBe("Bearer test-session");
    expect(timeout).toHaveBeenCalledWith(135_000);
    timeout.mockRestore();
    expect((await POST(new Request("http://localhost/api", { method: "POST", body: "x".repeat(16385) }), context("v1/agent/bill"))).status).toBe(413);
    expect((await GET(new Request("http://localhost/api"), context("v1/agent/bill"))).status).toBe(404);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("fails closed without backend configuration and rejects arbitrary paths", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "");
    expect((await POST(new Request("http://localhost/api", { method: "POST" }), context("v1/sessions"))).status).toBe(503);
    expect((await GET(new Request("http://localhost/api"), context("../../secrets"))).status).toBe(404);
  });
  it("forwards only the session credential and JSON body", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000");
    const fetcher = vi.fn().mockResolvedValue(Response.json({ status: "approval_required" }, { status: 201 }));
    vi.stubGlobal("fetch", fetcher);
    const response = await POST(new Request("http://localhost/api", { method: "POST", body: '{"daily_gallons":150}',
      headers: { authorization: "Bearer test-session", cookie: "private=value" } }), context("v1/goals/proposals"));
    expect(response.status).toBe(201);
    expect(response.headers.get("cache-control")).toBe("no-store");
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toBe("http://localhost:8000/v1/goals/proposals");
    expect(options.headers.get("authorization")).toBe("Bearer test-session");
    expect(options.headers.has("cookie")).toBe(false);
    expect(options.body).toBe('{"daily_gallons":150}');
  });
  it("limits request bodies and sanitizes connection errors", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000");
    const fetcher = vi.fn().mockRejectedValue(new Error("internal details"));
    vi.stubGlobal("fetch", fetcher);
    expect((await POST(new Request("http://localhost/api", { method: "POST", body: "x".repeat(1025) }), context("v1/goals/proposals"))).status).toBe(413);
    expect(fetcher).not.toHaveBeenCalled();
    const response = await GET(new Request("http://localhost/api"), context("v1/goals/current"));
    expect(response.status).toBe(503);
    expect(await response.text()).not.toContain("internal details");
  });
  it("relays only POST agent turns with a larger bounded body and model timeout", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000");
    const fetcher = vi.fn().mockResolvedValue(Response.json({ status: "answer" }));
    vi.stubGlobal("fetch", fetcher);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const body = JSON.stringify({ text: "q".repeat(2000), scenario_id: "irrigation-after-rain" });
    const response = await POST(new Request("http://localhost/api", { method: "POST", body,
      headers: { authorization: "Bearer test-session", cookie: "private=value" } }), context("v1/agent/turn"));
    expect(response.status).toBe(200);
    expect(fetcher.mock.calls[0][0]).toBe("http://localhost:8000/v1/agent/turn");
    expect(fetcher.mock.calls[0][1].body).toBe(body);
    expect(fetcher.mock.calls[0][1].headers.has("cookie")).toBe(false);
    expect(timeout).toHaveBeenCalledWith(135_000);
    timeout.mockRestore();
    expect((await GET(new Request("http://localhost/api"), context("v1/agent/turn"))).status).toBe(404);
  });
  it("stops oversized streamed agent bodies before calling the backend", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000");
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const result = await POST(new Request("http://localhost/api", { method: "POST", body: "x".repeat(16385) }), context("v1/agent/turn"));
    expect(result.status).toBe(413);
    expect(result.headers.get("cache-control")).toBe("no-store");
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("allows POST continuation with a model timeout while keeping its body limit small", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000");
    const fetcher = vi.fn().mockResolvedValue(Response.json({ status: "answer" }));
    vi.stubGlobal("fetch", fetcher);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const body = '{"approval_id":"12345678-abcd-1234-abcd-123456789abc"}';
    const result = await POST(new Request("http://localhost/api", { method: "POST", body }), context("v1/agent/continue"));
    expect(result.status).toBe(200);
    expect(fetcher.mock.calls[0][0]).toBe("http://localhost:8000/v1/agent/continue");
    expect(fetcher.mock.calls[0][1].body).toBe(body);
    expect(timeout).toHaveBeenCalledWith(135_000);
    timeout.mockRestore();
    expect((await POST(new Request("http://localhost/api", { method: "POST", body: "x".repeat(1025) }), context("v1/agent/continue"))).status).toBe(413);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect((await GET(new Request("http://localhost/api"), context("v1/agent/continue"))).status).toBe(404);
  });
  it("relays bill normalization with session auth, no cookies and the one-KiB limit", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000");
    const fetcher = vi.fn().mockResolvedValue(Response.json({ source: "manual_entry" }));
    vi.stubGlobal("fetch", fetcher);
    const body = JSON.stringify({ period_start: "2026-06-01", period_end_exclusive: "2026-07-01",
      usage: "3000", usage_unit: "us_gallons" });
    const response = await POST(new Request("http://localhost/api", { method: "POST", body,
      headers: { authorization: "Bearer test-session", cookie: "private=value" } }), context("v1/bills/normalize"));
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetcher.mock.calls[0][0]).toBe("http://localhost:8000/v1/bills/normalize");
    expect(fetcher.mock.calls[0][1].body).toBe(body);
    expect(fetcher.mock.calls[0][1].headers.get("authorization")).toBe("Bearer test-session");
    expect(fetcher.mock.calls[0][1].headers.has("cookie")).toBe(false);
    expect((await GET(new Request("http://localhost/api"), context("v1/bills/normalize"))).status).toBe(404);
    expect((await POST(new Request("http://localhost/api", { method: "POST", body: "x".repeat(1025) }),
      context("v1/bills/normalize"))).status).toBe(413);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
