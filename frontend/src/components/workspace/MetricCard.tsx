"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Code2,
  MinusCircle,
  Rocket,
  ShieldCheck,
  Verified,
  XCircle,
} from "lucide-react";
import { scoreTone, type ScorecardMetric, type ScorecardStatus } from "@/lib/projects/metrics";
import { cn } from "@/lib/ui/cn";

const TONE_CLASSES = {
  success: { stroke: "stroke-medha-success", text: "text-medha-success-ink", fill: "fill-medha-success-ink" },
  warning: { stroke: "stroke-medha-warning", text: "text-medha-warning", fill: "fill-medha-warning" },
  danger: { stroke: "stroke-medha-danger", text: "text-medha-danger", fill: "fill-medha-danger" },
  neutral: { stroke: "stroke-medha-border-strong", text: "text-medha-tertiary", fill: "fill-medha-tertiary" },
} as const;

const ICONS = {
  "code-quality": Code2,
  security: ShieldCheck,
  verification: Verified,
  readiness: Rocket,
} as const;

const STATUS_ICONS = {
  healthy: CheckCircle2,
  warning: AlertTriangle,
  critical: XCircle,
  not_assessed: MinusCircle,
  stale: Clock3,
} as const;

const STATUS_CLASSES: Record<ScorecardStatus, string> = {
  healthy: "text-medha-success-ink",
  warning: "text-medha-warning",
  critical: "text-medha-danger",
  not_assessed: "text-medha-tertiary",
  stale: "text-medha-warning",
};

function formatMs(ts: string | null): string | null {
  if (!ts) return null;
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Restrained count-up: animates once toward the real value, then stays still. */
function useCountUp(target: number | null): number | null {
  const [shown, setShown] = useState<number | null>(target);
  const first = useRef(true);
  useEffect(() => {
    if (target == null) {
      setShown(null);
      return;
    }
    if (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setShown(target);
      return;
    }
    if (first.current) {
      first.current = false;
    }
    const from = 0;
    const start = performance.now();
    const dur = 550;
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / dur);
      const eased = 1 - (1 - t) * (1 - t);
      setShown(Math.round(from + (target - from) * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target]);
  return shown;
}

/** Compact semicircular 0-100 gauge. `pathLength=100` keeps the dash math trivial. */
function Gauge({ value, label }: { value: number | null; label: string }) {
  const tone = TONE_CLASSES[scoreTone(value)];
  const shown = useCountUp(value);
  const clamped = shown == null ? null : Math.max(0, Math.min(100, shown));
  return (
    <svg
      viewBox="0 0 120 66"
      className="h-[68px] w-[118px] shrink-0"
      role="img"
      aria-label={value == null ? `${label}: not assessed` : `${label}: ${value} of 100`}
    >
      <path
        d="M 14 60 A 46 46 0 0 1 106 60"
        pathLength={100}
        fill="none"
        strokeWidth={7}
        strokeLinecap="round"
        className="stroke-medha-border"
      />
      {clamped != null ? (
        <path
          d="M 14 60 A 46 46 0 0 1 106 60"
          pathLength={100}
          fill="none"
          strokeWidth={7}
          strokeLinecap="round"
          strokeDasharray={`${clamped} ${100 - clamped}`}
          className={cn("medha-gauge-arc", tone.stroke)}
        />
      ) : null}
      <text
        x="60"
        y="55"
        textAnchor="middle"
        className={cn(
          "font-display text-[22px] font-semibold",
          clamped == null ? "fill-medha-tertiary" : tone.fill,
        )}
      >
        {clamped == null ? "—" : clamped}
      </text>
    </svg>
  );
}

export function MetricCard({ metric }: { metric: ScorecardMetric }) {
  const assessed = formatMs(metric.assessedAt);
  const Icon = ICONS[metric.id] ?? Code2;
  const StatusIcon = STATUS_ICONS[metric.status];
  const toneText =
    metric.value == null || metric.stale
      ? "text-medha-tertiary"
      : TONE_CLASSES[scoreTone(metric.value)].text;
  const coverage = metric.coverage
    ? `Checks completed: ${metric.coverage.assessed}/${metric.coverage.applicable} checks`
    : null;
  const revisionNote = [
    assessed ? `Assessed ${assessed}` : "No assessment recorded",
    metric.revision ? metric.revision : null,
    metric.stale ? "not current revision" : null,
    metric.refreshing ? "new assessment in progress" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Link
      href={metric.href}
      /* Compact card shows title, gauge, status and the findings action.
         Coverage, timestamp and revision stay available to assistive tech
         here and in full on the linked detail views. */
      aria-label={`${metric.title}: ${
        metric.value == null ? "not assessed" : `${metric.value} of 100`
      }, ${metric.statusLabel}. ${metric.evidence}${coverage ? `. ${coverage}` : ""}. ${revisionNote}`}
      data-status={metric.status}
      className={cn(
        "group flex h-full flex-col rounded-lg border bg-medha-surface p-3.5 text-left transition hover:border-medha-accent/50 hover:bg-medha-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent",
        metric.status === "not_assessed" && "border-dashed border-medha-border-strong",
        metric.status === "stale" && "border-medha-warning/40",
        metric.status === "critical" && "border-medha-danger/30",
        metric.status !== "not_assessed" && metric.status !== "stale" && metric.status !== "critical" && "border-medha-border",
      )}
    >
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 h-4 w-4 shrink-0 text-medha-secondary" aria-hidden />
        <p className="min-w-0 flex-1 text-[14.5px] font-semibold leading-5 text-medha-text">{metric.title}</p>
        {metric.isDemo ? (
          <span className="shrink-0 rounded border border-medha-border bg-medha-surface-muted px-1.5 py-0.5 text-[11.5px] font-semibold text-medha-secondary">DEMO</span>
        ) : null}
      </div>

      <div className="mt-1.5 flex items-center justify-center">
        <Gauge value={metric.value} label={metric.title} />
      </div>

      <p className={cn("text-center text-[14px] font-semibold leading-5", toneText)}>
        {metric.value == null ? "Not assessed" : `${metric.value}/100`}
      </p>

      {/* Status and action share one bottom row; status truncates so the
          findings link never overflows at narrow widths. */}
      <div className="mt-auto flex items-center justify-between gap-2 border-t border-medha-border pt-2.5">
        <span
          className={cn(
            "flex min-w-0 items-center gap-1.5 text-[12.5px] font-semibold leading-5",
            STATUS_CLASSES[metric.status],
          )}
        >
          <StatusIcon className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="truncate">{metric.statusLabel}</span>
        </span>
        <span className="shrink-0 text-[12.5px] font-semibold text-medha-accent">
          View findings <span aria-hidden>→</span>
        </span>
      </div>
    </Link>
  );
}
