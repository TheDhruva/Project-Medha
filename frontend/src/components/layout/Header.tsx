"use client";

import Link from "next/link";
import { Show, UserButton, SignInButton } from "@clerk/nextjs";
import { cn } from "@/lib/ui/cn";

// Inlined at build time: keyless builds (Render before Clerk secrets are set)
// have no ClerkProvider, and Clerk components throw without one — even at
// prerender. Guest mode simply hides the account controls.
const CLERK_ON = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

/* Route chrome: the project display name is resolved by the AppShell from
   the projects API (or a legacy repository URL) — never derived from the
   project ID, which would surface opaque `prj_*` identifiers. */
export function Header({
  projectName,
  pending = false,
}: {
  projectName: string | null;
  pending?: boolean;
}) {
  return (
    <header className="sticky top-0 z-40 h-14 shrink-0 border-b border-medha-border bg-medha-surface">
      <div className="mx-auto flex h-full w-full max-w-[1600px] items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
        <div className="flex min-w-0 items-center gap-2">
          <Link
            href="/projects"
            className="shrink-0 rounded-md px-2 py-1.5 font-display text-[15px] font-bold tracking-tight text-medha-text transition hover:text-medha-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
          >
            MEDHA
          </Link>

          {projectName || pending ? (
            <span className="flex min-w-0 items-center gap-2">
              <span aria-hidden className="h-4 w-px shrink-0 bg-medha-border" />
              <span
                className={cn(
                  "max-w-[38vw] truncate text-[13.5px] font-medium sm:max-w-[28rem]",
                  projectName ? "text-medha-secondary" : "text-medha-tertiary",
                )}
                title={projectName ?? undefined}
              >
                {projectName ?? "Loading project…"}
              </span>
            </span>
          ) : null}
        </div>

        <div className="flex shrink-0 items-center gap-3">
          {/* Account controls (hidden without Clerk keys — guest mode) */}
          {CLERK_ON && (
            <Show when="signed-out">
              <SignInButton mode="modal">
                <button
                  type="button"
                  className="rounded-full px-2.5 py-0.5 text-[12px] font-medium text-medha-secondary transition-colors hover:bg-medha-surface-muted hover:text-medha-text"
                >
                  Sign in
                </button>
              </SignInButton>
            </Show>
          )}
          {CLERK_ON && (
            <Show when="signed-in">
              <UserButton />
            </Show>
          )}
        </div>
      </div>
    </header>
  );
}
