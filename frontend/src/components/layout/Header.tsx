"use client";

import Link from "next/link";
import { Show, UserButton, SignInButton, SignUpButton } from "@clerk/nextjs";
import { useOptionalDeployment } from "@/context/DeploymentContext";
import { cn } from "@/lib/ui/cn";

export function Header() {
  const deployment = useOptionalDeployment();
  const snapshot = deployment?.snapshot;
  const form = deployment?.form;
  const isDemo = (form?.mode === "demo" || snapshot?.isDemo) ?? true;
  const isRunning = snapshot?.runStatus === "running";

  // Project name: use the deployment form's repository URL context, or fall
  // back to the demo project name.
  const projectLabel = isDemo
    ? "Atlas Commerce"
    : snapshot?.explain?.technicalText
      ? `${snapshot.explain.technicalText.slice(0, 30)}…`
      : "My Project";

  return (
    <header
      className="min-h-[64px] bg-medha-surface border-b border-medha-flexible flex items-center justify-between px-4 sm:px-6"
    >
      <div className="flex items-center gap-2 max-w-7xl w-full mx-auto">
        <div className="flex items-center gap-2">
          <Link
            href={isDemo ? "/" : "/projects"}
            className="rounded-md px-3 py-1.5 text-sm font-medium transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
          >
            <span className="text-[15px] font-bold tracking-tight text-medha-text">
              MEDHA
            </span>
          </Link>

          {isDemo ? (
            <span className="text-[12px] text-medha-secondary truncate">Atlas Commerce</span>
          ) : (
            <span className="text-[12px] text-medha-secondary truncate">{projectLabel}</span>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <span
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold",
              isDemo ? "border-medha-border bg-medha-surface-muted text-medha-tertiary" : "border-medha-border bg-medha-surface-soft text-medha-secondary",
            )}
            title={
              deployment
                ? isDemo
                  ? "Demo Mode uses labelled fixtures"
                  : "Real Mode local pipeline"
                  : "Default environment"
            }
          >
            <span
              className={cn("status-dot", isDemo ? "bg-medha-tertiary" : "bg-medha-tertiary")}
              aria-hidden
            />
            {isDemo ? "DEMO" : "LIVE"}
          </span>

          {/* Primary new-run action — only in demo mode when no run is actively open */}
          {isDemo && !isRunning && (
            <button
              type="button"
              onClick={() => window.location.pathname = "/runs/new"}
              className="rounded-md px-3 py-1.5 text-[10px] font-medium text-medha-accent hover:bg-medha-accent-soft text-medha-accent-ink transition-colors"
              title="Start new DEMO run"
            >
              New run
            </button>
          )}

          {/* Account controls */}
          <Show when="signed-out">
            <SignInButton mode="modal">
              <button
                type="button"
                className="rounded-full px-2.5 py-0.5 text-[11px] font-medium text-medha-secondary transition-colors hover:bg-medha-surface-muted hover:text-medha-text"
              >
                Sign in
              </button>
            </SignInButton>
          </Show>
          <Show when="signed-in">
            <UserButton />
          </Show>
        </div>
      </div>
    </header>
  );
}