"use client";

import { useState } from "react";
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  ChevronDown,
  ArrowRight,
} from "lucide-react";
import type { DeploymentSnapshot } from "@/lib/demo/types";
import { getDecision, getJourney } from "@/lib/run/decision";
import { EnvBadge, ExecutionModeBadge } from "@/components/ui/Section";
import { cn } from "@/lib/ui/cn";

export function DecisionCard({
  snapshot,
  onViewEvidence,
  onViewRecovery,
}: {
  snapshot: DeploymentSnapshot;
  onViewEvidence: () => void;
  onViewRecovery: () => void;
}) {
  const decision = getDecision(snapshot);
  const Icon =
    decision.kind === "approved"
      ? CheckCircle2
      : decision.kind === "blocked"
        ? XCircle
        : decision.kind === "recovered"
          ? AlertTriangle
          : Loader2;
  const iconClass =
    decision.kind === "approved"
      ? "text-medha-success"
      : decision.kind === "blocked"
        ? "text-medha-danger"
        : decision.kind === "recovered"
          ? "text-medha-warning"
          : "animate-spin text-medha-run";
  const panelClass =
    decision.kind === "approved"
      ? "border-medha-success/25"
      : decision.kind === "blocked"
        ? "border-medha-danger/25"
        : decision.kind === "recovered"
          ? "border-medha-warning/30"
          : "border-medha-border";

  return (
    <section
      aria-label="Deployment decision"
      className={cn("rounded-xl border bg-white p-5 sm:p-6", panelClass)}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <Icon className={cn("mt-0.5 h-6 w-6 shrink-0", iconClass)} aria-hidden />
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-medha-tertiary">
              Decision
            </p>
            <h2 className="mt-0.5 text-xl font-bold tracking-tight text-medha-text sm:text-2xl">
              {decision.title}
            </h2>
            {decision.score != null ? (
              <p className="mt-1 text-sm font-semibold text-medha-text" aria-label={`Score ${decision.score} out of 100`}>
                {decision.score} <span className="font-normal text-medha-tertiary">/ 100</span>
              </p>
            ) : (
              <p className="mt-1 text-sm text-medha-tertiary">Not evaluated yet</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <EnvBadge isDemo={snapshot.isDemo} />
          <ExecutionModeBadge mode={snapshot.executionMode} />
        </div>
      </div>
      <p className="mt-3 max-w-2xl text-sm leading-relaxed text-medha-secondary">
        {decision.body}
      </p>
      {decision.risk ? (
        <p className="mt-2 text-xs text-medha-secondary">
          Risk: <span className="font-semibold capitalize text-medha-text">{decision.risk}</span>
        </p>
      ) : null}
      <div className="mt-4">
        <button
          type="button"
          onClick={decision.kind === "recovered" ? onViewRecovery : onViewEvidence}
          className="inline-flex items-center gap-1.5 rounded-lg border border-medha-border bg-white px-4 py-2 text-sm font-medium text-medha-text transition hover:bg-medha-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
        >
          {decision.cta} <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
    </section>
  );
}

export function JourneyCard({ snapshot }: { snapshot: DeploymentSnapshot }) {
  const steps = getJourney(snapshot);
  return (
    <section aria-label="Verification journey" className="rounded-xl border border-medha-border bg-white p-5 sm:p-6">
      <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-medha-tertiary">
        Verification journey
      </p>
      <ol className="mt-3">
        {steps.map((s, i) => (
          <li key={s.label} className="relative flex gap-3 pb-4 last:pb-0">
            {i < steps.length - 1 ? (
              <span
                className={cn(
                  "absolute left-[7px] top-5 h-[calc(100%-16px)] w-px",
                  s.done ? "bg-medha-success/40" : "bg-medha-border",
                )}
                aria-hidden
              />
            ) : null}
            <span
              className={cn(
                "mt-1 h-[15px] w-[15px] shrink-0 rounded-full border-2",
                s.done
                  ? "border-medha-success bg-medha-success"
                  : s.active
                    ? "animate-medha-pulse border-medha-run bg-medha-run"
                    : "border-medha-border bg-white",
              )}
              aria-hidden
            />
            <span
              className={cn(
                "text-sm",
                s.done ? "font-medium text-medha-text" : s.active ? "font-medium text-medha-text" : "text-medha-tertiary",
              )}
            >
              {s.done ? "✓ " : ""}{s.label}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function SummaryRow({ snapshot }: { snapshot: DeploymentSnapshot }) {
  const files = snapshot.changeIntel?.changeset.files.length;
  const counts = snapshot.changeIntel?.changeset.counts;
  const totalFiles =
    files ?? (counts ? counts.modified + counts.added + counts.deleted + counts.renamed : null);
  const services =
    snapshot.changeIntel != null
      ? new Set([
          ...snapshot.changeIntel.traversal.direct_targets,
          ...snapshot.changeIntel.traversal.transitive_targets,
        ]).size
      : snapshot.graph.nodes.length > 0
        ? new Set(snapshot.graph.nodes.map((n) => n.service)).size
        : null;
  const checks = snapshot.verification?.checks;
  const conflicts = snapshot.constraints.filter(
    (c) => c.status === "conflict" || c.status === "superseded" || c.status === "rejected",
  ).length;
  const hasNegotiation = snapshot.negotiation != null || snapshot.constraints.length > 0;
  const duration = snapshot.result?.durationLabel;

  const items: Array<{ label: string; value: string }> = [];
  if (totalFiles != null) items.push({ label: "Files changed", value: `${totalFiles}` });
  if (services != null) items.push({ label: "Services affected", value: `${services}` });
  if (checks && checks.length > 0) {
    const passed = checks.filter((c) => c.status === "pass").length;
    items.push({ label: "Checks", value: `${passed} / ${checks.length}` });
  }
  if (hasNegotiation) {
    items.push({
      label: "Conflicts",
      value: conflicts > 0 ? `${conflicts} resolved` : "None",
    });
  }
  if (duration && duration !== "—") items.push({ label: "Duration", value: duration });

  if (items.length === 0) return null;
  return (
    <section aria-label="Run summary" className="rounded-xl border border-medha-border bg-white px-5 py-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-medha-tertiary">
        Run summary
      </p>
      <dl className="mt-2 flex flex-wrap gap-x-8 gap-y-2">
        {items.map((item) => (
          <div key={item.label} className="min-w-[90px]">
            <dt className="text-xs text-medha-secondary">{item.label}</dt>
            <dd className="text-[15px] font-semibold text-medha-text">{item.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function SectionShell({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-medha-border bg-white p-5 sm:p-6">
      <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-medha-tertiary">
        {eyebrow}
      </p>
      <h2 className="mt-1 text-lg font-semibold tracking-tight text-medha-text">{title}</h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function CollapsibleShell({
  eyebrow,
  title,
  preview,
  actionLabel,
  defaultOpen = false,
  children,
}: {
  eyebrow: string;
  title: string;
  preview?: string;
  actionLabel?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="overflow-hidden rounded-xl border border-medha-border bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left transition hover:bg-medha-muted/50"
      >
        <span className="min-w-0">
          <span className="block text-[11px] font-semibold uppercase tracking-[0.1em] text-medha-tertiary">
            {eyebrow}
          </span>
          <span className="mt-0.5 block text-[15px] font-semibold text-medha-text">{title}</span>
          {!open && preview ? (
            <span className="mt-0.5 block truncate text-[13px] text-medha-secondary">{preview}</span>
          ) : null}
          {!open && actionLabel ? (
            <span className="mt-1 inline-flex items-center gap-1 text-[13px] font-medium text-medha-accent">
              {actionLabel} <ChevronDown className="h-3.5 w-3.5" aria-hidden />
            </span>
          ) : null}
        </span>
        <ChevronDown
          className={cn("h-4 w-4 shrink-0 text-medha-secondary transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>
      {open ? <div className="border-t border-medha-border px-5 py-4">{children}</div> : null}
    </section>
  );
}
