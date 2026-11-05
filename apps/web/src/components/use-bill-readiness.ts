"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { waitForBillReadiness } from "@/lib/bill-readiness";

export function useBillReadiness() {
  const [status, setStatus] = useState<"starting" | "ready" | "unavailable">("starting");
  const pending = useRef<{ controller: AbortController; promise: Promise<void> } | null>(null);
  const check = useCallback(() => {
    if (pending.current && !pending.current.controller.signal.aborted) return pending.current.promise;
    const controller = new AbortController();
    setStatus("starting");
    const promise = waitForBillReadiness(controller.signal).then(() => {
      controller.signal.throwIfAborted();
      setStatus("ready");
    }, (error) => {
      if (!controller.signal.aborted) setStatus("unavailable");
      throw error;
    }).finally(() => {
      if (pending.current?.controller === controller) pending.current = null;
    });
    pending.current = { controller, promise };
    return promise;
  }, []);
  useEffect(() => {
    void check().catch(() => {});
    return () => pending.current?.controller.abort();
  }, [check]);
  return { status, check };
}
