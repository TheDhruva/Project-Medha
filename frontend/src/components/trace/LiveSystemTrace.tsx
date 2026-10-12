"use client";

import { useDeployment } from "@/context/DeploymentContext";
import { runSourceLabel } from "@/lib/ui/status";

const toneClass = {
  success: "text-medha-success",
  warning: "text-medha-warning",
  error: "text-medha-danger",
  info: "text-medha-run",
  neutral: "text-medha-secondary",
} as const;

export function LiveSystemTrace() {
  const { form, snapshot, viewMode } = useDeployment();
  // Render window: newest 200 only. Full history (≤500 in state, more via
  // REST logs) stays accessible; mounting thousands of <li> per SSE event
  // was the dominant rerender cost.
  const events = snapshot.trace.slice(-200).reverse();
  const truncated = snapshot.trace.length > 200;
  const source = runSourceLabel(form.mode, snapshot.isDemo);

  return (
    <section className="medha-panel animate-medha-in flex max-h-[420px] flex-col p-4 sm:p-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
          LIVE SYSTEM TRACE
        </h2>
        <span className="rounded-full bg-medha-warning-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-medha-warning">
          {source} events
        </span>
      </div>

      {events.length === 0 ? (
        <p className="rounded-medha-sm border border-dashed border-medha-border bg-medha-muted/40 px-3 py-8 text-center text-sm text-medha-secondary">
          No events yet. Start a deployment to stream the {source} timeline.
        </p>
      ) : (
        <>
          {truncated ? (
            <p className="mb-2 text-[11px] text-medha-tertiary">
              Showing latest 200 of {snapshot.trace.length} events. Full history via run logs.
            </p>
          ) : null}
          <ol className="space-y-0 overflow-y-auto pr-1">
          {events.map((event, index) => (
            <li
              key={event.id}
              className="relative border-l border-medha-border py-2.5 pl-4 animate-medha-in"
              style={{ animationDelay: `${Math.min(index, 8) * 20}ms` }}
            >
              <span
                className={`absolute -left-[5px] top-3.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-current ${toneClass[event.tone]}`}
                aria-hidden
              />
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <time className="medha-mono text-[11px] text-medha-tertiary">{event.time}</time>
                <p className={`text-sm ${toneClass[event.tone]}`}>
                  <span aria-hidden className="mr-1">
                    {event.tone === "success"
                      ? "✓"
                      : event.tone === "warning"
                        ? "⚠"
                        : event.tone === "error"
                          ? "✕"
                          : "→"}
                  </span>
                  {event.message}
                </p>
              </div>
              {viewMode === "technical" && event.technical ? (
                <p className="medha-mono mt-1 text-[10px] text-medha-tertiary">
                  {event.technical}
                </p>
              ) : null}
            </li>
          ))}
          </ol>
        </>
      )}
    </section>
  );
}