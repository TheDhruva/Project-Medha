"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/ui/cn";

export function Section({
  eyebrow,
  title,
  description,
  action,
  children,
  className,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-xl border border-medha-border bg-medha-surface p-5 sm:p-6", className)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {eyebrow ? (
            <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-medha-tertiary">
              {eyebrow}
            </p>
          ) : null}
          <h2 className="mt-1 text-lg font-semibold tracking-tight text-medha-text">{title}</h2>
          {description ? (
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-medha-secondary">
              {description}
            </p>
          ) : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function Collapsible({
  title,
  eyebrow,
  description,
  defaultOpen = false,
  children,
  actionLabel,
}: {
  title: string;
  eyebrow?: string;
  description?: string;
  defaultOpen?: boolean;
  children: ReactNode;
  actionLabel?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="overflow-hidden rounded-xl border border-medha-border bg-medha-surface">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left transition hover:bg-medha-surface-raised focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
      >
        <span className="min-w-0">
          {eyebrow ? (
            <span className="block text-[11px] font-semibold uppercase tracking-[0.1em] text-medha-tertiary">
              {eyebrow}
            </span>
          ) : null}
          <span className="mt-0.5 block text-[15px] font-semibold text-medha-text">{title}</span>
          {description && !open ? (
            <span className="mt-0.5 block truncate text-[13px] text-medha-secondary">
              {description}
            </span>
          ) : null}
          {actionLabel && !open ? (
            <span className="mt-1 inline-block text-[13px] font-medium text-medha-accent">
              {actionLabel}
            </span>
          ) : null}
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-medha-secondary transition-transform",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>
      {open ? (
        <div className="border-t border-medha-border px-5 py-4">
          {description ? (
            <p className="mb-3 text-sm text-medha-secondary">{description}</p>
          ) : null}
          {children}
        </div>
      ) : null}
    </section>
  );
}

export function EnvBadge({ isDemo, size = "md" }: { isDemo: boolean; size?: "sm" | "md" }) {  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border font-semibold",
        size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-[11px]",
        isDemo
          ? "border-medha-border bg-medha-muted text-medha-secondary"
          : "border-medha-run/25 bg-medha-run-soft text-medha-run-ink",
      )}
      title={isDemo ? "Deterministic demo fixture" : "Real backend data"}
    >
      <span
        className={cn("status-dot", isDemo ? "bg-medha-tertiary" : "bg-medha-run")}
        aria-hidden
      />
      {isDemo ? "DEMO" : "LIVE"}
    </span>
  );
}

/**
 * How the run actually executed, from GET /logs `execution_mode`.
 * Distinct from EnvBadge (demo-data vs backend-data): a non-demo run may
 * still be simulated. Renders nothing when the mode is unknown.
 */
export function ExecutionModeBadge({
  mode,
  size = "md",
}: {
  mode: string | null | undefined;
  size?: "sm" | "md";
}) {
  const label =
    mode === "real"
      ? "REAL"
      : mode === "controlled_test"
        ? "CONTROLLED TEST"
        : mode === "simulator"
          ? "SIMULATED"
          : mode === "demo"
            ? "DEMO"
            : null;
  if (!label) return null;
  const hot = mode === "real";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border font-semibold",
        size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-[11px]",
        hot
          ? "border-medha-success/30 bg-medha-success-soft text-medha-success"
          : "border-medha-border bg-medha-muted text-medha-secondary",
      )}
      title={
        mode === "real"
          ? "Built and ran in the isolated runtime with a blocking readiness gate"
          : mode === "controlled_test"
            ? "Controlled local execution (BusyBox), not a full application build"
            : mode === "simulator"
              ? "Deterministic simulation — no containers were started"
              : "Deterministic demo fixture"
      }
    >
      <span
        className={cn("status-dot", hot ? "bg-medha-success" : "bg-medha-tertiary")}
        aria-hidden
      />
      {label}
    </span>
  );
}

export function StatusBadge({
  tone,
  icon,
  children,
}: {
  tone: "success" | "warning" | "error" | "info" | "neutral";
  icon?: ReactNode;
  children: ReactNode;
}) {
  const cls =
    tone === "success"
      ? "border-medha-success/30 bg-medha-success-soft text-medha-success"
      : tone === "warning"
        ? "border-medha-warning/30 bg-medha-warning-soft text-medha-warning"
        : tone === "error"
          ? "border-medha-danger/30 bg-medha-danger-soft text-medha-danger"
          : tone === "info"
            ? "border-medha-run/25 bg-medha-run-soft text-medha-run-ink"
            : "border-medha-border bg-medha-muted text-medha-secondary";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold",
        cls,
      )}
    >
      {icon}
      {children}
    </span>
  );
}
