import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

const TOKEN_HEADER = "X-Medha-Token";
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/**
 * Clerk auth + MEDHA server-side API token injection.
 *
 * Clerk handles session/auth state for all matched routes. The MEDHA token
 * logic is preserved unchanged: attach the server-side API token to mutating
 * /api/* requests before the next.config.js rewrite proxies them to FastAPI.
 *
 * The token lives only in server env (MEDHA_API_TOKEN): browsers call the
 * same origin with no credentials, so the secret never enters the client
 * bundle. When no token is configured the request passes through unchanged —
 * the backend then allows it locally, or fails closed when MEDHA_ENV is
 * production. Streaming (SSE) is untouched: this middleware never reads the
 * request/response body.
 */
export default clerkMiddleware((_auth, request) => {
  if (!MUTATING_METHODS.has(request.method)) {
    return NextResponse.next();
  }
  const token = process.env.MEDHA_API_TOKEN;
  if (!token) {
    return NextResponse.next();
  }
  const headers = new Headers(request.headers);
  headers.set(TOKEN_HEADER, token);
  return NextResponse.next({ request: { headers } });
});

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    "/__clerk/:path*",
  ],
};
