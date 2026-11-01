// Check the web-to-API connection without creating a session or calling a model.
export const dynamic = "force-dynamic";

export async function GET() {
  const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
  const unavailable = () => Response.json({ status: "unavailable" }, { status: 503, headers });
  const base = process.env.AQUAMIND_API_URL;
  if (!base) return unavailable();
  try {
    const response = await fetch(`${base.replace(/\/$/, "")}/health`, {
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(5_000),
    });
    if (!response.ok || (await response.json())?.status !== "ok") return unavailable();
    return Response.json({ status: "ok" }, { headers });
  } catch {
    return unavailable();
  }
}
