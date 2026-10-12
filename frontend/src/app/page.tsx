"use client";

import { useAuth } from "@clerk/nextjs";
import { LandingPage } from "@/components/landing/LandingPage";
import { Skeleton } from "@/components/ui/primitives";
import { ProjectHub } from "@/components/workspace/ProjectHub";

/**
 * Entry flow: Landing page first (for all users),
 * signed-in users see "Start" to proceed to project selection,
 * guests see Sign In / Continue as Guest options.
 *
 * CLERK_ON is inlined at build time. Keyless builds (e.g. Render before
 * Clerk dashboard secrets are set) render guest mode without touching
 * useAuth, which would throw outside a ClerkProvider during prerender.
 */
const CLERK_ON = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

export default function HomePage() {
  if (!CLERK_ON) {
    return <LandingPage signedIn={false} />;
  }
  return <AuthedHome />;
}

function AuthedHome() {
  const { isLoaded, isSignedIn } = useAuth();

  if (!isLoaded) {
    return (
      <div className="mx-auto max-w-6xl space-y-3 px-4 py-10 sm:px-6" aria-label="Loading">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (isSignedIn) {
    return <LandingPage signedIn={true} />;
  }
  return <LandingPage signedIn={false} />;
}
