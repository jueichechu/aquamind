/** Bounded, read-only startup checks. Never creates a session or sends a report. */
export const BILL_STARTUP_UNAVAILABLE = "Bill analysis could not start. Your report has not been sent. Try again or enter details instead.";
const STARTUP_WINDOW_MS = 120_000;
const POLL_INTERVAL_MS = 10_000;

function pause(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(signal.reason); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, ms);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
}

export async function waitForBillReadiness(signal: AbortSignal): Promise<void> {
  const deadline = Date.now() + STARTUP_WINDOW_MS;
  while (Date.now() < deadline) {
    signal.throwIfAborted();
    let delay = POLL_INTERVAL_MS;
    try {
      const response = await fetch("/api/aquamind/v1/bills/readiness", {
        method: "GET", credentials: "omit", cache: "no-store",
        // A Free backend can take roughly a minute to wake. Keep one probe alive
        // beyond the relay's 70-second cold-start allowance, within this window.
        signal: AbortSignal.any([signal, AbortSignal.timeout(Math.min(75_000, deadline - Date.now()))]),
      });
      if (response.ok && (await response.json())?.status === "ready") {
        signal.throwIfAborted();
        return;
      }
      // Configuration/route failures cannot be solved by repeated checks.
      if ([401, 403, 404].includes(response.status)) break;
      const retry = response.headers.get("retry-after");
      if ([429, 503].includes(response.status) && retry && /^[1-9]\d{0,5}$/.test(retry)) {
        delay = Math.max(delay, Number(retry) * 1000);
      }
    } catch {
      signal.throwIfAborted();
      // Startup/network failures may be retried only on this read-only endpoint.
    }
    const remaining = deadline - Date.now();
    if (delay >= remaining) break;
    await pause(delay, signal);
  }
  throw new Error(BILL_STARTUP_UNAVAILABLE);
}
