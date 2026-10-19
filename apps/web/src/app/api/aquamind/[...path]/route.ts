// Only these demo endpoints are exposed through the same-origin relay.
const allowed = new Set([
  "POST v1/sessions", "DELETE v1/session", "GET v1/goals/current", "POST v1/goals/proposals", "POST v1/agent/turn",
]);

class RequestTooLarge extends Error {}
const safeHeaders = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const failure = (detail: string, status: number) => Response.json({ detail }, { status, headers: safeHeaders });

async function boundedBody(request: Request, limit: number) {
  const reader = request.body?.getReader();
  if (!reader) return undefined;
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > limit) {
        await reader.cancel();
        throw new RequestTooLarge();
      }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return new TextDecoder().decode(bytes);
}

async function relay(request: Request, context: { params: Promise<{ path: string[] }> }) {
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
  const agent = route === "v1/agent/turn";
  try {
    const body = request.method === "POST" ? await boundedBody(request, agent ? 16384 : 1024) : undefined;
    const headers = new Headers({ "Content-Type": "application/json" });
    const auth = request.headers.get("authorization");
    if (auth) headers.set("Authorization", auth);
    const upstream = await fetch(`${base.replace(/\/$/, "")}/${route}`, {
      method: request.method, headers, body, cache: "no-store", redirect: "error",
      signal: AbortSignal.timeout(agent ? 135_000 : 10_000),
    });
    return new Response(upstream.status === 204 ? null : await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json", ...safeHeaders },
    });
  } catch (cause) {
    if (cause instanceof RequestTooLarge) return failure("Request too large", 413);
    return failure(agent ? "Agent request could not be confirmed" : "Demo backend unavailable", 503);
  }
}

export const GET = relay;
export const POST = relay;
export const DELETE = relay;
