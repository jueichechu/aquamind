import { IMPORT_BODY_LIMIT } from "../../../../lib/bill-import";

// Only these application endpoints are exposed through the same-origin relay.
const allowed = new Set([
  "POST v1/sessions", "DELETE v1/session", "GET v1/goals/current", "POST v1/goals/proposals",
  "POST v1/agent/turn", "POST v1/agent/continue", "POST v1/agent/bill",
  "POST v1/bills/normalize", "POST v1/bills/import", "POST v1/bills/compare",
]);

class RequestTooLarge extends Error {}
class RequestBodyTimedOut extends Error {}
const safeHeaders = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const failure = (detail: string, status: number, extraHeaders = {}) =>
  Response.json({ detail }, { status, headers: { ...safeHeaders, ...extraHeaders } });
let activePublicRequests = 0;

async function boundedBody(request: Request, limit: number) {
  const reader = request.body?.getReader();
  if (!reader) return undefined;
  const chunks: Uint8Array[] = [];
  let length = 0;
  let timer: ReturnType<typeof setTimeout>;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new RequestBodyTimedOut()), 15_000);
  });
  async function consume() {
    while (true) {
      const { value, done } = await reader!.read();
      if (done) break;
      length += value.byteLength;
      if (length > limit) {
        throw new RequestTooLarge();
      }
      chunks.push(value);
    }
  }
  try {
    // Race the whole read once so tiny chunks cannot accumulate timeout listeners.
    await Promise.race([consume(), deadline]);
  } catch (cause) {
    // A slow stream's cancel hook must not extend the request deadline.
    void reader.cancel().catch(() => {});
    throw cause;
  } finally { clearTimeout(timer!); reader.releaseLock(); }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return new TextDecoder().decode(bytes);
}

async function forward(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join("/");
  const approval = /^v1\/approvals\/[0-9a-f-]{36}$/.test(route);
  const decision = /^v1\/approvals\/[0-9a-f-]{36}\/decision$/.test(route);
  if (!allowed.has(`${request.method} ${route}`) &&
      !(request.method === "GET" && approval) && !(request.method === "POST" && decision)) {
    return failure("Unknown endpoint", 404);
  }
  const base = process.env.AQUAMIND_API_URL;
  if (!base) return failure("Demo backend unavailable", 503);
  const newTurn = route === "v1/agent/turn" || route === "v1/agent/bill";
  const importing = route === "v1/bills/import";
  const comparing = route === "v1/bills/compare";
  const agent = newTurn || route === "v1/agent/continue" || importing;
  try {
    const limit = importing ? IMPORT_BODY_LIMIT : newTurn ? 16384 : comparing ? 12 * 1024 : 1024;
    const body = request.method === "POST" ? await boundedBody(request, limit) : undefined;
    const headers = new Headers({ "Content-Type": "application/json" });
    const auth = request.headers.get("authorization");
    if (auth) headers.set("Authorization", auth);
    const upstream = await fetch(`${base.replace(/\/$/, "")}/${route}`, {
      method: request.method, headers, body, cache: "no-store", redirect: "error",
      signal: AbortSignal.timeout(agent ? 135_000 : 10_000),
    });
    const responseHeaders: Record<string, string> = { "Content-Type": "application/json", ...safeHeaders };
    const retry = upstream.headers.get("retry-after");
    if (upstream.status === 429 && retry && /^[1-9]\d{0,5}$/.test(retry)) responseHeaders["Retry-After"] = retry;
    return new Response(upstream.status === 204 ? null : await upstream.text(), {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (cause) {
    if (cause instanceof RequestTooLarge) return failure("Request too large", 413);
    if (cause instanceof RequestBodyTimedOut) return failure("Request body timed out", 408);
    return failure(agent ? "Agent request could not be confirmed" : "Demo backend unavailable", 503);
  }
}

async function relay(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const mode = process.env.AQUAMIND_PUBLIC_MODE ?? "0";
  if (mode !== "0" && mode !== "1") return failure("Demo backend unavailable", 503);
  const limited = mode === "1";
  if (limited && activePublicRequests >= 8) return failure("Service busy; try again later", 429, { "Retry-After": "1" });
  if (limited) activePublicRequests += 1;
  try { return await forward(request, context); }
  finally { if (limited) activePublicRequests -= 1; }
}

export const GET = relay;
export const POST = relay;
export const DELETE = relay;
