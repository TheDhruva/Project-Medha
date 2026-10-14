"use client";

import Link from "next/link";
import { scoreTone, type ScorecardMetric } from "@/lib/projects/metrics";
import { cn } from "@/lib/ui/cn";

const TONE_CLASSES = {
  success: { stroke: "stroke-medha-success", text: "text-medha-success-ink", fill: "fill-medha-success-ink" },
  warning: { stroke: "stroke-medha-warning", text: "text-medha-warning", fill: "fill-medha-warning" },
  danger: { stroke: "stroke-medha-danger", text: "text-medha-danger", fill: "fill-medha-danger" },
  neutral: { stroke: "stroke-medha-border-strong", text: "text-medha-tertiary", fill: "fill-medha-tertiary" },
} as const;

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

/** Semicircular 0-100 gauge. `pathLength=100` makes the dash math trivial. */
function Gauge({ value, label }: { value: number | null; label: string }) {
  const tone = TONE_CLASSES[scoreTone(value)];
  const clamped = value == null ? null : Math.max(0, Math.min(100, value));
  return (
    <svg
      viewBox="0 0 120 66"
      className="h-16 w-[120px] shrink-0"
      role="img"
      aria-label={clamped == null ? `${label}: not assessed` : `${label}: ${clamped} of 100`}
    >
      <path
        d="M 14 60 A 46 46 0 0 1 106 60"
        pathLength={100}
        fill="none"
        strokeWidth={9}
        strokeLinecap="round"
        className="stroke-medha-border"
      />
      {clamped != null ? (
        <path
          d="M 14 60 A 46 46 0 0 1 106 60"
          pathLength={100}
          fill="none"
          strokeWidth={9}
          strokeLinecap="round"
          strokeDasharray={`${clamped} ${100 - clamped}`}
          className={cn("transition-[stroke-dasharray] duration-500", tone.stroke)}
        />
      ) : null}
      <text
        x="60"
        y="54"
        textAnchor="middle"
        className={cn(
          "font-display text-[19px] font-bold",
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
  return (
    <Link
      href={metric.href}
      className="group flex flex-col rounded-lg border border-medha-border bg-medha-surface p-3.5 text-left transition hover:border-medha-accent/50 hover:bg-medha-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="medha-label">{metric.title}</p>
          <p
            className={cn(
              "mt-1 text-[13px] font-semibold",
              metric.value == null ? "text-medha-tertiary" : TONE_CLASSES[scoreTone(metric.value)].text,
            )}
          >
            {metric.value == null ? "Not assessed" : `${metric.value}/100`}
          </p>
          {metric.isDemo ? (
            <p className="mt-0.5 text-[10px] font-semibold text-medha-tertiary">DEMO/MOCK</p>
          ) : null}
        </div>
        <Gauge value={metric.value} label={metric.title} />
      </div>
      <p className="mt-1 line-clamp-2 min-h-[32px] text-[12px] leading-snug text-medha-secondary">
        {metric.evidence}
      </p>
      <p className="mt-1 truncate text-[11px] text-medha-tertiary">
        {assessed ? `Assessed ${assessed}` : "No assessment recorded"}
        {metric.revision ? ` · ${metric.revision}` : ""}
      </p>
    </Link>
  );
}
