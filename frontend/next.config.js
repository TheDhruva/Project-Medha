const path = require("path");

// Internal FastAPI origin for the /api/* and /health rewrites below.
//
// IMPORTANT: Next.js evaluates rewrites() at BUILD time and bakes the
// destination into the production build — a runtime MEDHA_BACKEND_URL is NOT
// picked up by `next start` (verified by smoke test: proxying to a
// runtime-only port returns 500). The single-service topology therefore uses
// a fixed loopback backend port: scripts/run_service.py and the Dockerfile
// both default MEDHA_BACKEND_PORT to 8000. Keep this value in sync with them.
const BACKEND_URL = "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  outputFileTracingRoot: path.join(__dirname),
  // Trim first-load JS: lucide-react + xyflow ship per-module so page
  // bundles include only imported icons/graph code.
  experimental: {
    optimizePackageImports: ["lucide-react", "@xyflow/react"],
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` },
      { source: "/health", destination: `${BACKEND_URL}/health` },
    ];
  },
  // Baseline hardening headers. Plain static pages and same-origin
  // fetch/EventSource are unaffected; nothing here changes app behavior.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
