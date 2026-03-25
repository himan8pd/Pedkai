import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export for cloud deployment (Caddy serves the files).
  // Set NEXT_OUTPUT_EXPORT=true during cloud build; leave unset for local dev.
  ...(process.env.NEXT_OUTPUT_EXPORT === "true" ? { output: "export" } : {}),

  // Force relative API paths for production builds, ignoring any .env files
  // that might contain local or HTTP URLs. Caddy proxies /api/* to the backend.
  ...(process.env.NEXT_OUTPUT_EXPORT === "true" ? {
    env: {
      NEXT_PUBLIC_API_BASE_URL: "",
    }
  } : {}),
};

export default nextConfig;
