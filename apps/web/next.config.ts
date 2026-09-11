import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  // The repo root also has its own package-lock.json (for the Playwright
  // E2E harness in tests/e2e), which Next.js would otherwise mistake for a
  // second workspace root.
  turbopack: { root: path.join(__dirname) },
};

export default nextConfig;
