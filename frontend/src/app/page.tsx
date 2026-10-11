"use client";

import { useAuth } from "@clerk/nextjs";
import { LandingPage } from "@/components/landing/LandingPage";
import { Skeleton } from "@/components/ui/primitives";
import { ProjectHub } from "@/components/workspace/ProjectHub";

/**
 * Entry flow: Landing page first (for all users),
 * signed-in users see "Start" to proceed to project selection,
 * guests see Sign In / Continue as Guest options.
 */
export default function HomePage() {
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
