// Only these demo endpoints are exposed through the same-origin relay.
const allowed = new Set([
  "POST v1/sessions", "DELETE v1/session", "GET v1/goals/current", "POST v1/goals/proposals",
]);

async function relay(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join("/");
  const approval = /^v1\/approvals\/[0-9a-f-]{36}$/.test(route);
  const decision = /^v1\/approvals\/[0-9a-f-]{36}\/decision$/.test(route);
  if (!allowed.has(`${request.method} ${route}`) &&
      !(request.method === "GET" && approval) && !(request.method === "POST" && decision)) {
    return Response.json({ detail: "Unknown endpoint" }, { status: 404 });
  }
  const base = process.env.AQUAMIND_API_URL;
  if (!base) return Response.json({ detail: "Demo backend unavailable" }, { status: 503 });
  try {
    const body = request.method === "POST" ? await request.text() : undefined;
    if (body && new TextEncoder().encode(body).length > 1024) {
      return Response.json({ detail: "Request too large" }, { status: 413 });
    }
    const headers = new Headers({ "Content-Type": "application/json" });
    const auth = request.headers.get("authorization");
    if (auth) headers.set("Authorization", auth);
    const upstream = await fetch(`${base.replace(/\/$/, "")}/${route}`, {
      method: request.method, headers, body, cache: "no-store", redirect: "error",
      signal: AbortSignal.timeout(10_000),
    });
    return new Response(upstream.status === 204 ? null : await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
    });
  } catch {
    return Response.json({ detail: "Demo backend unavailable" }, { status: 503 });
  }
}

export const GET = relay;
export const POST = relay;
export const DELETE = relay;
