import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  agentRules: false,
  // The container serves exported pages from Python; local Next.js development
  // retains its existing server routes and relay.
  ...(process.env.AQUAMIND_STATIC_EXPORT === "1"
    ? { output: "export" as const }
    : {}),
};

export default nextConfig;
