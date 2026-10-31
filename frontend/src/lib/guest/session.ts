/**
 * Guest sessions (server-issued, no account).
 *
 * The token lives in `sessionStorage`, so it survives navigation and same-tab
 * reloads and is dropped when the tab/browser closes. That is only transport
 * persistence — the backend owns the session: it issues the token, stores only
 * its SHA-256, validates it on every request, expires it, and purges
 * everything the guest owned. Nothing here is trusted as identity.
 *
 * The token is sent in the `Authorization` header only, never in a URL.
 *
 * Deliberately self-contained (no import from `@/lib/api/client`) so the API
 * client can fall back to this token without a circular import.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "";

const GUEST_TOKEN_KEY = "medha.guest.token";

export interface GuestSession {
  token: string;
  session_id: string;
  subject: string;
  expires_at: string;
  mode: string;
}

export function getGuestToken(): string | null {
  try {
    return window.sessionStorage.getItem(GUEST_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setGuestToken(token: string): void {
  try {
    window.sessionStorage.setItem(GUEST_TOKEN_KEY, token);
  } catch {
    /* Private mode / storage disabled — the session simply will not persist. */
  }
}

export function clearGuestToken(): void {
  try {
    window.sessionStorage.removeItem(GUEST_TOKEN_KEY);
  } catch {
    /* noop */
  }
}

function guestHeaders(token: string | null, extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

async function errorFrom(response: Response, fallback: string): Promise<Error> {
  try {
    const body = await response.json();
    return new Error(body?.error?.message || fallback);
  } catch {
    return new Error(fallback);
  }
}

/**
 * Ask the backend to mint a guest session and keep the returned token.
 * Throws with a user-readable message when the backend refuses.
 */
export async function createGuestSession(): Promise<GuestSession> {
  const response = await fetch(`${API_BASE}/api/guest-session`, {
    method: "POST",
    // Same-origin proxy injects the MEDHA API token server-side.
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw await errorFrom(response, "Could not start a guest session.");
  }
  const session = (await response.json()) as GuestSession;
  setGuestToken(session.token);
  return session;
}

/** Server-side check that the stored token still maps to a live session. */
export async function verifyGuestSession(): Promise<boolean> {
  const token = getGuestToken();
  if (!token) return false;
  const response = await fetch(`${API_BASE}/api/guest-session`, {
    headers: guestHeaders(token),
    cache: "no-store",
  });
  if (!response.ok) {
    clearGuestToken();
    return false;
  }
  return true;
}

/**
 * End the guest session and purge its data on the backend.
 *
 * Always clears the local token, even when the request fails: a token the
 * backend no longer accepts is useless. Returns false when the backend could
 * not confirm cleanup, so callers never claim a deletion that did not happen.
 */
export async function endGuestSession(): Promise<boolean> {
  const token = getGuestToken();
  if (!token) return true;
  let ok = false;
  try {
    const response = await fetch(`${API_BASE}/api/guest-session`, {
      method: "DELETE",
      headers: guestHeaders(token),
      credentials: "same-origin",
    });
    ok = response.ok;
  } catch {
    ok = false;
  }
  clearGuestToken();
  return ok;
}
