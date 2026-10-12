import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextRequest, NextResponse } from "next/server";

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
 *
 * Without Clerk keys (e.g. Render build/preview before dashboard secrets are
 * set) Clerk's middleware would throw on every request, so fall back to
 * token-only injection. Guest demo keeps working; protected routes just see
 * signed-out state.
 */
function injectApiToken(request: NextRequest) {
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
}

const clerkHandler = clerkMiddleware((_auth, request) => injectApiToken(request));

const hasClerkKeys =
  !!process.env.CLERK_SECRET_KEY ||
  !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

export default hasClerkKeys ? clerkHandler : injectApiToken;

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    "/__clerk/:path*",
  ],
};
