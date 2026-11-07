"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect } from "react";
import { registerAuthTokenGetter } from "@/lib/api/client";
import { endGuestSession, getGuestToken } from "@/lib/guest/session";

/**
 * Bridges Clerk browser sessions to the FastAPI authorization layer.
 *
 * Registers an async getter that resolves the current Clerk session JWT for
 * every API call (see apiFetch). When signed out the getter returns null and
 * requests fall back to the guest session token.
 *
 * Guest work is never merged into an account: when a Clerk session appears
 * while a guest token is still stored, the guest session is ended server-side
 * (its data is purged, not migrated) and the local token is dropped.
 */
export function ClerkTokenSync() {
  const { getToken, isSignedIn, isLoaded } = useAuth();

  useEffect(() => {
    if (!isLoaded) return;

    registerAuthTokenGetter(async () => {
      if (!isSignedIn) return null;
      try {
        return await getToken();
      } catch {
        return null;
      }
    });
    return () => registerAuthTokenGetter(null);
  }, [getToken, isSignedIn, isLoaded]);

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !getGuestToken()) return;
    void endGuestSession();
  }, [isLoaded, isSignedIn]);

  return null;
}
