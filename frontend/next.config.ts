import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export for cloud deployment (Caddy serves the files).
  // Set NEXT_OUTPUT_EXPORT=true during cloud build; leave unset for local dev.
  ...(process.env.NEXT_OUTPUT_EXPORT === "true" ? { output: "export" } : {}),
};

export default nextConfig;
