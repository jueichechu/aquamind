import { afterEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "./route";
const context = (path: string) => ({ params: Promise.resolve({ path: path.split("/") }) });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });
describe("approval relay", () => {
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
});
