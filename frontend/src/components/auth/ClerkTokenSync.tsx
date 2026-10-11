"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect } from "react";
import { registerAuthTokenGetter } from "@/lib/api/client";

/**
 * Bridges Clerk browser sessions to the FastAPI authorization layer.
 *
 * Registers an async getter that resolves the current Clerk session JWT for
 * every API call (see apiFetch). When signed out the getter returns null and
 * requests proceed unauthenticated (guest demo). Renders nothing.
 */
export function ClerkTokenSync() {
  const { getToken, isSignedIn } = useAuth();

  useEffect(() => {
    registerAuthTokenGetter(async () => {
      if (!isSignedIn) return null;
      try {
        return await getToken();
      } catch {
        return null;
      }
    });
    return () => registerAuthTokenGetter(null);
  }, [getToken, isSignedIn]);

  return null;
}
