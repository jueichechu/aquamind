import { afterEach, describe, expect, it, vi } from "vitest";
import { DELETE, GET, POST } from "./route";
import { IMPORT_BODY_LIMIT } from "../../../../lib/bill-import";
import { AUDIO_BODY_LIMIT } from "../../../../lib/voice";
const context = (path: string) => ({ params: Promise.resolve({ path: path.split("/") }) });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.useRealTimers(); });
describe("approval relay", () => {
  it("relays bounded meter imports and session-local reads/clears with the existing credentials", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "https://api.example");
    vi.stubEnv("AQUAMIND_RELAY_REQUIRED", "1");
    const secret = "server-only-meter-placeholder-".repeat(2);
    vi.stubEnv("AQUAMIND_RELAY_SECRET", secret);
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(Response.json({ context: { origin: "user_provided" } })));
    vi.stubGlobal("fetch", fetcher);
    const body = JSON.stringify({ csv_text: "x".repeat(2048) });
    const result = await POST(new Request("http://localhost/api", { method: "POST", body,
      headers: { Authorization: "Bearer visitor-session", "X-AquaMind-Relay-Key": "forged", Cookie: "private=value" },
    }), context("v1/meters/import"));
    expect(result.status).toBe(200);
    expect(result.headers.get("cache-control")).toBe("no-store");
    expect(fetcher.mock.calls[0][0]).toBe("https://api.example/v1/meters/import");
    expect(fetcher.mock.calls[0][1].body).toBe(body);
    expect(fetcher.mock.calls[0][1].headers.get("authorization")).toBe("Bearer visitor-session");
    expect(fetcher.mock.calls[0][1].headers.get("x-aquamind-relay-key")).toBe(secret);
    expect(fetcher.mock.calls[0][1].headers.has("cookie")).toBe(false);
    expect((await GET(new Request("http://localhost/api"), context("v1/meters/current"))).status).toBe(200);
    fetcher.mockResolvedValue(new Response(null, { status: 204 }));
    expect((await DELETE(new Request("http://localhost/api", { method: "DELETE" }), context("v1/meters/current"))).status).toBe(204);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect((await POST(new Request("http://localhost/api", { method: "POST" }), context("v1/meters/current"))).status).toBe(404);
    expect((await GET(new Request("http://localhost/api"), context("v1/meters/import"))).status).toBe(404);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("bounds actual meter import bytes before forwarding", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "https://api.example");
    const fetcher = vi.fn().mockResolvedValue(Response.json({}));
    vi.stubGlobal("fetch", fetcher);
    const limit = 96 * 1024;
    const request = (body: string) => new Request("http://localhost/api", {
      method: "POST", body, headers: { "Content-Length": "1" },
    });
    expect((await POST(request(" ".repeat(limit)), context("v1/meters/import"))).status).toBe(200);
    expect((await POST(request(" ".repeat(limit - 1) + "é"), context("v1/meters/import"))).status).toBe(413);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it.each([
    [200, "text/html", "<html>private edge error</html>"],
    [429, "text/plain", "private edge error"],
    [503, "text/html", "<html>private startup page</html>"],
    [200, "application/json", '{"status":"ok"}'],
    [200, "application/json", '{"status":"ready","private":"data"}'],
    [200, "text/plain", '{"status":"ready"}'],
    [200, "application/json", '"ready"'],
    [200, "application/json", 'not json'],
    [204, "application/json", null],
  ])("normalizes invalid readiness responses to unavailable (%s, %s)", async (status, type, body) => {
    vi.stubEnv("AQUAMIND_API_URL", "https://api.example");
    const fetcher = vi.fn().mockResolvedValue(new Response(body, { status, headers: { "Content-Type": type } }));
    vi.stubGlobal("fetch", fetcher);
    const result = await GET(new Request("http://localhost/api"), context("v1/bills/readiness"));
    expect(result.status).toBe(503);
    expect(await result.json()).toEqual({ detail: "Bill analysis unavailable" });
    expect(result.headers.get("cache-control")).toBe("no-store");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("bounds readiness response bytes and cancels an oversized stream", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "https://api.example");
    const cancelled = vi.fn();
    const stream = new ReadableStream({ start(controller) {
      controller.enqueue(new Uint8Array(1025));
    }, cancel: cancelled });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(stream, { headers: { "Content-Type": "application/json" } })));
    const result = await GET(new Request("http://localhost/api"), context("v1/bills/readiness"));
    expect(result.status).toBe(503);
    expect(await result.json()).toEqual({ detail: "Bill analysis unavailable" });
    expect(cancelled).toHaveBeenCalledTimes(1);
  });

  it.each([401, 404, 429, 503])("preserves valid readiness application errors (%s)", async (status) => {
    vi.stubEnv("AQUAMIND_API_URL", "https://api.example");
    const body = { detail: "Application unavailable", request_id: "12345678-abcd-1234-abcd-123456789abc" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(body, { status })));
    const result = await GET(new Request("http://localhost/api"), context("v1/bills/readiness"));
    expect(result.status).toBe(status);
    expect(await result.json()).toEqual(body);
  });

  it.each([[429, "30", "30"], [503, "60", "60"], [503, "private-host", null], [503, "1000000", null]])(
    "keeps only bounded cooldown hints when normalizing an upstream readiness page (%s)", async (status, retry, expected) => {
      vi.stubEnv("AQUAMIND_API_URL", "https://api.example");
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("private edge page", {
        status, headers: { "Retry-After": retry, "Content-Type": "text/html" },
      })));
      const result = await GET(new Request("http://localhost/api"), context("v1/bills/readiness"));
      expect(result.status).toBe(503);
      expect(result.headers.get("retry-after")).toBe(expected);
      expect(await result.json()).toEqual({ detail: "Bill analysis unavailable" });
    });

  it("relays bill readiness without a session and keeps the method allowlist", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "https://api.example");
    vi.stubEnv("AQUAMIND_RELAY_REQUIRED", "1");
    vi.stubEnv("AQUAMIND_RELAY_SECRET", "server-only-placeholder-".repeat(2));
    const fetcher = vi.fn().mockResolvedValue(Response.json({ status: "ready" }));
    vi.stubGlobal("fetch", fetcher);
    const result = await GET(new Request("http://localhost/api"), context("v1/bills/readiness"));
    expect(result.status).toBe(200);
    expect(await result.json()).toEqual({ status: "ready" });
    expect(result.headers.get("cache-control")).toBe("no-store");
    expect(fetcher.mock.calls[0][0]).toBe("https://api.example/v1/bills/readiness");
    expect(fetcher.mock.calls[0][1].method).toBe("GET");
    expect(fetcher.mock.calls[0][1].headers.has("authorization")).toBe(false);
    expect(fetcher.mock.calls[0][1].body).toBeUndefined();
    expect((await POST(new Request("http://localhost/api", { method: "POST" }), context("v1/bills/readiness"))).status).toBe(404);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("cancels a cold-start readiness request when its visitor leaves", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "https://api.example");
    const controller = new AbortController();
    const fetcher = vi.fn().mockImplementation((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(options.signal.reason), { once: true });
    }));
    vi.stubGlobal("fetch", fetcher);
    const pending = GET(new Request("https://website.example/api", { signal: controller.signal }),
      context("v1/bills/readiness"));
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    controller.abort();
    expect((await pending).status).toBe(503);
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it("supplies server relay credentials while ignoring browser-supplied credentials", async () => {
    const secret = "server-only-test-key-".repeat(2);
    vi.stubEnv("AQUAMIND_API_URL", "https://api.example");
    vi.stubEnv("AQUAMIND_RELAY_REQUIRED", "1");
    vi.stubEnv("AQUAMIND_RELAY_SECRET", secret);
    const fetcher = vi.fn().mockResolvedValue(Response.json({ session_token: "session" }));
    vi.stubGlobal("fetch", fetcher);
    const result = await POST(new Request("http://localhost/api", { method: "POST", body: "{}",
      headers: { "X-AquaMind-Relay-Key": "browser-controlled", cookie: "private=value" },
    }), context("v1/sessions"));
    expect(result.status).toBe(200);
    expect(fetcher.mock.calls[0][1].headers.get("x-aquamind-relay-key")).toBe(secret);
    expect(fetcher.mock.calls[0][1].headers.has("cookie")).toBe(false);
    expect(await result.text()).not.toContain(secret);
    expect(result.headers.has("x-aquamind-relay-key")).toBe(false);
  });

  it.each([["1", ""], ["1", "short"], ["1", "a".repeat(129)], ["1", " ".repeat(40)], ["invalid", ""]])(
    "fails closed before upstream work with relay settings %s", async (required, secret) => {
      vi.stubEnv("AQUAMIND_RELAY_REQUIRED", required);
      vi.stubEnv("AQUAMIND_RELAY_SECRET", secret);
      const fetcher = vi.fn();
      vi.stubGlobal("fetch", fetcher);
      expect((await POST(new Request("http://localhost/api"), context("v1/sessions"))).status).toBe(503);
      expect(fetcher).not.toHaveBeenCalled();
    });

  it("bounds public in-flight uploads and releases every timed-out reader without forwarding", async () => {
    vi.useFakeTimers();
    vi.stubEnv("AQUAMIND_PUBLIC_MODE", "1");
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000");
    const fetcher = vi.fn().mockResolvedValue(Response.json({}));
    vi.stubGlobal("fetch", fetcher);
    // A malicious stream may also stall its cancellation hook.
    const cancelled = vi.fn(() => new Promise<void>(() => {}));
    const pending = Array.from({ length: 8 }, () => POST(new Request("http://localhost/api", {
      method: "POST", body: new ReadableStream({ cancel: cancelled }), duplex: "half",
    } as RequestInit), context("v1/bills/import")));
    const denied = await POST(new Request("http://localhost/api", { method: "POST", body: "{}" }), context("v1/sessions"));
    expect(denied.status).toBe(429);
    expect(denied.headers.get("retry-after")).toBe("1");
    await vi.advanceTimersByTimeAsync(15_000);
    for (const response of await Promise.all(pending)) {
      expect(response.status).toBe(408);
      expect(await response.json()).toEqual({ detail: "Request body timed out" });
    }
    expect(cancelled).toHaveBeenCalledTimes(8);
    expect(fetcher).not.toHaveBeenCalled();
    const recovered = await POST(new Request("http://localhost/api", { method: "POST", body: "{}" }), context("v1/sessions"));
    expect(recovered.status).toBe(200);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("fails closed on invalid public-mode settings", async () => {
    vi.stubEnv("AQUAMIND_PUBLIC_MODE", "invalid");
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    expect((await POST(new Request("http://localhost/api"), context("v1/sessions"))).status).toBe(503);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("forwards only bounded numeric Retry-After values on throttled responses", async () => {
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000");
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    for (const [status, retry, expected] of [[429, "60", "60"], [429, "86400", "86400"],
      [429, "private-host", null], [429, "1000000", null], [200, "60", null]] as const) {
      fetcher.mockResolvedValueOnce(Response.json({}, { status, headers: { "Retry-After": retry } }));
      const result = await POST(new Request("http://localhost/api", { method: "POST", body: "{}" }), context("v1/sessions"));
      expect(result.status).toBe(status);
      expect(result.headers.get("retry-after")).toBe(expected);
    }
  });

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
  it.each(['bills/import','audio/transcribe'])("bounds %s separately and preserves no-store, auth and the paid request deadline", async (route) => {
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000");
    const fetcher = vi.fn().mockResolvedValue(Response.json({ needs_review: true }));
    vi.stubGlobal("fetch", fetcher);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const body = JSON.stringify({ media_type: "application/pdf", data_base64: "x".repeat(20000), share_with_ai: true });
    const response = await POST(new Request("http://localhost/api", { method: "POST", body,
      headers: { authorization: "Bearer test-session", cookie: "private=value" } }), context(`v1/${route}`));
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetcher.mock.calls[0][0]).toBe(`http://localhost:8000/v1/${route}`);
    expect(fetcher.mock.calls[0][1].body).toBe(body);
    expect(fetcher.mock.calls[0][1].headers.has("cookie")).toBe(false);
    expect(timeout).toHaveBeenCalledWith(135_000); timeout.mockRestore();
    expect((await POST(new Request("http://localhost/api", { method: "POST", body: "x".repeat((route==='audio/transcribe'?AUDIO_BODY_LIMIT:IMPORT_BODY_LIMIT) + 1) }),
      context(`v1/${route}`))).status).toBe(413);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect((await GET(new Request("http://localhost/api"), context(`v1/${route}`))).status).toBe(404);
  });
  it.each(['agent/bill','agent/evidence'])("relays %s with a model deadline, bounded body and no browser cookies", async (route) => {
    vi.stubEnv("AQUAMIND_API_URL", "http://localhost:8000");
    const fetcher = vi.fn().mockResolvedValue(Response.json({ status: "answer" }));
    vi.stubGlobal("fetch", fetcher);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const body = JSON.stringify({ text: "q".repeat(2000), bill: { usage: "8.5" }, is_example: true, share_with_ai: true });
    expect((await POST(new Request("http://localhost/api", { method: "POST", body,
      headers: { authorization: "Bearer test-session", cookie: "private=value" } }), context(`v1/${route}`))).status).toBe(200);
    expect(fetcher.mock.calls[0][0]).toBe(`http://localhost:8000/v1/${route}`);
    expect(fetcher.mock.calls[0][1].body).toBe(body);
    expect(fetcher.mock.calls[0][1].headers.has("cookie")).toBe(false);
    expect(fetcher.mock.calls[0][1].headers.get("authorization")).toBe("Bearer test-session");
    expect(timeout).toHaveBeenCalledWith(135_000);
    timeout.mockRestore();
    expect((await POST(new Request("http://localhost/api", { method: "POST", body: "x".repeat(16385) }), context(`v1/${route}`))).status).toBe(413);
    expect((await GET(new Request("http://localhost/api"), context(`v1/${route}`))).status).toBe(404);
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
