import { afterEach, describe, expect, it, vi } from "vitest";
import { DELETE, GET, POST } from "./route";
import { IMPORT_BODY_LIMIT } from "../../../../lib/bill-import";
const context = (path: string) => ({ params: Promise.resolve({ path: path.split("/") }) });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });
describe("approval relay", () => {
  it("relays bill comparisons with a twelve-KiB limit, session auth and a calculation deadline", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000/");
    const payload = { evidence_level: "historical_bills", request_id: "test-request" };
    const fetcher = vi.fn().mockImplementation(async () => Response.json(payload));
    vi.stubGlobal("fetch", fetcher);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    try {
      const body = JSON.stringify({ bills: Array.from({ length: 12 }, (_, index) => ({
        period_start: `2026-01-${String(index + 1).padStart(2, "0")}`,
        period_end_exclusive: `2026-01-${String(index + 2).padStart(2, "0")}`,
        usage: "100.123456", usage_unit: "us_gallons",
      })) });
      expect(body.length).toBeGreaterThan(1024);
      const response = await POST(new Request("http://localhost/api", { method: "POST", body,
        headers: { authorization: "Bearer test-session", cookie: "private=value" } }), context("v1/bills/compare"));
      expect(response.status).toBe(200);
      expect(await response.json()).toEqual(payload);
      expect(response.headers.get("cache-control")).toBe("no-store");
      expect(response.headers.get("x-content-type-options")).toBe("nosniff");
      const [url, options] = fetcher.mock.calls[0];
      expect(url).toBe("http://localhost:8000/v1/bills/compare");
      expect(options.body).toBe(body);
      expect(options.headers.get("authorization")).toBe("Bearer test-session");
      expect(options.headers.has("cookie")).toBe(false);
      expect(options.cache).toBe("no-store");
      expect(options.redirect).toBe("error");
      expect(timeout).toHaveBeenCalledWith(10_000);
      for (const handler of [GET, DELETE]) {
        expect((await handler(new Request("http://localhost/api", {
          method: handler === GET ? "GET" : "DELETE",
        }), context("v1/bills/compare"))).status).toBe(404);
      }
      expect(fetcher).toHaveBeenCalledTimes(1);
    } finally { timeout.mockRestore(); }
  });
  it("bounds streamed comparison bytes without trusting Content-Length", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000");
    const fetcher = vi.fn().mockImplementation(async () => Response.json({}));
    vi.stubGlobal("fetch", fetcher);
    const limit = 12 * 1024;
    expect((await POST(new Request("http://localhost/api", {
      method: "POST", body: " ".repeat(limit),
    }), context("v1/bills/compare"))).status).toBe(200);
    expect(fetcher).toHaveBeenCalledTimes(1);
    const body = new ReadableStream({ start(controller) {
      controller.enqueue(new TextEncoder().encode(" ".repeat(limit - 1)));
      controller.enqueue(new TextEncoder().encode("é"));
      controller.close();
    } });
    const request = new Request("http://localhost/api", {
      method: "POST", body, headers: { "Content-Length": "1" }, duplex: "half",
    } as RequestInit);
    const response = await POST(request, context("v1/bills/compare"));
    expect(response.status).toBe(413);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("preserves comparison failures and never retries unavailable calculations", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000");
    const fetcher = vi.fn().mockImplementation(async () => Response.json({ detail: "Session unavailable" }, { status: 401 }));
    vi.stubGlobal("fetch", fetcher);
    const request = () => new Request("http://localhost/api", { method: "POST", body: '{"bills":[]}' });
    const denied = await POST(request(), context("v1/bills/compare"));
    expect(denied.status).toBe(401);
    expect(await denied.json()).toEqual({ detail: "Session unavailable" });
    fetcher.mockRejectedValueOnce(new Error("private upstream details"));
    const failed = await POST(request(), context("v1/bills/compare"));
    expect(failed.status).toBe(503);
    expect(await failed.json()).toEqual({ detail: "Demo backend unavailable" });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("bounds report import separately and preserves no-store, auth and the paid request deadline", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000");
    const fetcher = vi.fn().mockResolvedValue(Response.json({ needs_review: true }));
    vi.stubGlobal("fetch", fetcher);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const body = JSON.stringify({ media_type: "application/pdf", data_base64: "x".repeat(20000), share_with_ai: true });
    const response = await POST(new Request("http://localhost/api", { method: "POST", body,
      headers: { authorization: "Bearer test-session", cookie: "private=value" } }), context("v1/bills/import"));
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetcher.mock.calls[0][0]).toBe("http://localhost:8000/v1/bills/import");
    expect(fetcher.mock.calls[0][1].body).toBe(body);
    expect(fetcher.mock.calls[0][1].headers.has("cookie")).toBe(false);
    expect(timeout).toHaveBeenCalledWith(135_000); timeout.mockRestore();
    expect((await POST(new Request("http://localhost/api", { method: "POST", body: "x".repeat(IMPORT_BODY_LIMIT + 1) }),
      context("v1/bills/import"))).status).toBe(413);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect((await GET(new Request("http://localhost/api"), context("v1/bills/import"))).status).toBe(404);
  });
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
