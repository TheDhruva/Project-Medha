"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Code2, Rocket, ShieldCheck, Verified } from "lucide-react";
import { scoreTone, type ScorecardMetric } from "@/lib/projects/metrics";
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
          className={cn("medha-gauge-arc", tone.stroke)}
        />
      ) : null}
      <text
        x="60"
        y="55"
        textAnchor="middle"
        className={cn(
          "font-display text-[20px] font-bold",
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
  const toneText =
    metric.value == null ? "text-medha-tertiary" : TONE_CLASSES[scoreTone(metric.value)].text;
  return (
    <Link
      href={metric.href}
      aria-label={`${metric.title}: ${metric.value == null ? "not assessed" : `${metric.value} of 100`}. ${metric.evidence}`}
      className="group flex flex-col rounded-lg border border-medha-border bg-medha-surface p-3 text-left transition hover:border-medha-accent/50 hover:bg-medha-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
    >
      <div className="flex items-center gap-1.5">
        <Icon className="h-3.5 w-3.5 shrink-0 text-medha-secondary" aria-hidden />
        <p className="medha-label truncate">{metric.title}</p>
        {metric.isDemo ? (
          <span className="ml-auto shrink-0 text-[10px] font-semibold text-medha-tertiary">DEMO</span>
        ) : null}
      </div>
      <div className="mt-1 flex items-center justify-center">
        <Gauge value={metric.value} label={metric.title} />
      </div>
      <p className={cn("text-center text-[12.5px] font-semibold", toneText)}>
        {metric.value == null ? "Not assessed" : `${metric.value}/100`}
      </p>
      <p className="mt-1 line-clamp-2 min-h-[30px] text-center text-[11.5px] leading-snug text-medha-secondary">
        {metric.evidence}
      </p>
      <p className="mt-1 truncate text-center text-[10.5px] text-medha-tertiary">
        {assessed ? `Assessed ${assessed}` : "No assessment recorded"}
        {metric.revision ? ` · ${metric.revision}` : ""}
      </p>
    </Link>
  );
}
