"use client";

import { useMemo, useState } from "react";
import { useDeployment } from "@/context/DeploymentContext";
import { runSourceLabel } from "@/lib/ui/status";
import { cn } from "@/lib/ui/cn";
import type { TraceEvent } from "@/lib/demo/types";

const DOT = {
  success: "bg-medha-success",
  warning: "bg-medha-warning",
  error: "bg-medha-danger",
  info: "bg-medha-run",
  neutral: "bg-medha-border-strong",
} as const;

const GLYPH = {
  success: "✓",
  warning: "⚠",
  error: "✕",
  info: "→",
  neutral: "→",
} as const;

const RECENT_LIMIT = 12;

/** Noise filter: keep stage transitions, decisions, warnings, failures. */
function isMeaningful(e: TraceEvent): boolean {
  if (e.tone === "error" || e.tone === "warning") return true;
  return /stage|verif|cnp|negot|execut|deploy|health|rollback|critic|approv|fail|plan|analy|complete|ready|start/i.test(
    `${e.message} ${e.technical ?? ""}`,
  );
}

function concise(message: string, limit = 140): string {
  const oneLine = message.replace(/\s+/g, " ").trim();
  return oneLine.length > limit ? `${oneLine.slice(0, limit)}…` : oneLine;
}

/**
 * Readable Run Timeline: recent meaningful events with concise titles,
 * per-event expansion for full diagnostics, and a view-all disclosure.
 * No nested scroll container — the page scrolls. SSE dedupe happens in
 * the deployment context (event_id set); ids are deduped defensively here.
 */
export function LiveSystemTrace() {
  const { form, snapshot, viewMode } = useDeployment();
  const [showAll, setShowAll] = useState(false);
  const technical = viewMode === "technical";
  const source = runSourceLabel(form.mode, snapshot.isDemo);

  const events = useMemo(() => {
    const seen = new Set<string>();
    const ordered = [...snapshot.trace].reverse();
    const unique = ordered.filter((e) => {
      if (seen.has(e.id)) return false;
      seen.add(e.id);
      return true;
    });
    return technical ? unique : unique.filter(isMeaningful);
  }, [snapshot.trace, technical]);

  const visible = showAll ? events : events.slice(0, RECENT_LIMIT);

  return (
    <section className="medha-panel animate-medha-in p-4" aria-label="Run Timeline">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
          Run Timeline
        </h2>
        <span className="rounded-full bg-medha-warning-soft px-2 py-0.5 text-[12.5px] font-semibold uppercase tracking-wide text-medha-warning">
          {source} events · {events.length}
        </span>
      </div>

      {events.length === 0 ? (
        <p className="rounded-medha-sm border border-dashed border-medha-border bg-medha-muted/40 px-3 py-6 text-center text-sm text-medha-secondary">
          No events yet. Start a deployment to stream the {source} timeline.
        </p>
      ) : (
        <>
          <ol>
            {visible.map((event) => (
              <li key={event.id} className="relative border-l border-medha-border py-1.5 pl-4">
                <span
                  className={cn(
                    "absolute -left-[5px] top-2.5 h-2.5 w-2.5 rounded-full border-2 border-medha-surface",
                    DOT[event.tone],
                  )}
                  aria-hidden
                />
                <details>
                  <summary className="cursor-pointer list-none [&::-webkit-details-marker]:hidden">
                    <span className="flex flex-wrap items-baseline gap-x-2">
                      <time className="medha-mono shrink-0 text-[12px] text-medha-tertiary">{event.time}</time>
                      <span className="min-w-0 flex-1 text-[13px] text-medha-text">
                        <span aria-hidden className={cn("mr-1", DOT[event.tone].replace("bg-", "text-"))}>
                          {GLYPH[event.tone]}
                        </span>
                        {concise(event.message)}
                      </span>
                    </span>
                  </summary>
                  <div className="mt-1 rounded-medha-sm border border-medha-border bg-white px-2.5 py-1.5">
                    <p className="whitespace-pre-wrap break-words text-[12px] leading-relaxed text-medha-secondary">
                      {event.message}
                    </p>
                    {event.technical ? (
                      <p className="medha-mono mt-1 break-words text-[12px] text-medha-tertiary">
                        {event.technical}
                      </p>
                    ) : null}
                  </div>
                </details>
              </li>
            ))}
          </ol>
          {events.length > RECENT_LIMIT ? (
            <button
              type="button"
              onClick={() => setShowAll((v) => !v)}
              aria-expanded={showAll}
              className="mt-2 text-[12.5px] font-semibold text-medha-accent hover:underline"
            >
              {showAll ? "Show fewer events ↑" : `View all ${events.length} events →`}
            </button>
          ) : null}
        </>
      )}
    </section>
  );
}
