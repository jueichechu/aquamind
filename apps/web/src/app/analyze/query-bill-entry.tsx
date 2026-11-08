"use client";

import { useSearchParams } from "next/navigation";
import { BillEntry } from "./bill-entry";

export function QueryBillEntry() {
  const example = useSearchParams().get("example") === "1";
  return <BillEntry key={example ? "example" : "manual"} initialExample={example} />;
}
