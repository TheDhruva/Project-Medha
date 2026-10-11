"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Settings } from "lucide-react";
import { useOptionalDeployment } from "@/context/DeploymentContext";
import { cn } from "@/lib/ui/cn";

const NAV_ITEMS = [
  { href: "/", label: "Overview" },
  { href: "/verify", label: "Verify" },
  { href: "/runs", label: "Runs" },
  { href: "/evaluation", label: "Evaluation" },
];

export function Header() {
  const deployment = useOptionalDeployment();
  const pathname = usePathname() ?? "";
  const snapshot = deployment?.snapshot;
  const form = deployment?.form;
  // Compact global environment indicator: DEMO unless we know this is a real run.
  const isDemo = (form?.mode === "demo" || snapshot?.isDemo) ?? true;
  const isRunning = snapshot?.runStatus === "running";

  return (
    <header className="border-b border-medha-border bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-6">
          <Link
            href="/"
            className="rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
          >
            <span className="text-[17px] font-bold tracking-tight text-medha-text">
              MEDHA
            </span>
          </Link>
          <nav aria-label="Primary" className="flex items-center gap-1">
            {NAV_ITEMS.map((item) => {
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors",
                    active
                      ? "bg-medha-text text-white"
                      : "text-medha-secondary hover:bg-medha-muted hover:text-medha-text",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
            <Link
              href="/settings"
              aria-label="Settings"
              title="Settings"
              aria-current={pathname.startsWith("/settings") ? "page" : undefined}
              className={cn(
                "ml-1 rounded-full p-2 transition-colors",
                pathname.startsWith("/settings")
                  ? "bg-medha-text text-white"
                  : "text-medha-secondary hover:bg-medha-muted hover:text-medha-text",
              )}
            >
              <Settings className="h-4 w-4" aria-hidden />
            </Link>
          </nav>
        </div>

        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold",
            isDemo
              ? "border-medha-accent/25 bg-medha-accent-soft text-medha-accent-ink"
              : "border-medha-success/30 bg-medha-success-soft text-medha-success",
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
            className={cn("status-dot", isDemo ? "bg-medha-accent" : "bg-medha-success", isRunning && "animate-medha-pulse")}
            aria-hidden
          />
          {isDemo ? "DEMO" : "LIVE"}
        </span>
      </div>
    </header>
  );
}