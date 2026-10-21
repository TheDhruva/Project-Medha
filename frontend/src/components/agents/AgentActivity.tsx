"use client";

import { useDeployment } from "@/context/DeploymentContext";
import { labelStatus, statusGlyph } from "@/lib/ui/status";
import type { AgentStatus } from "@/lib/demo/types";
import { cn } from "@/lib/ui/cn";

const DOT: Record<AgentStatus, string> = {
  complete: "bg-medha-success",
  running: "bg-medha-run",
  failed: "bg-medha-danger",
  warning: "bg-medha-warning",
  skipped: "bg-medha-border-strong",
  idle: "bg-medha-border-strong",
};

function needsAttention(status: AgentStatus): boolean {
  return status === "running" || status === "failed" || status === "warning";
}

/**
 * Compact agent activity: one row per logical agent (name, status,
 * duration, latest meaningful action), expandable full output. Completed
 * agents collapse into a quiet group; active/failed stay prominent.
 */
export function AgentActivity() {
  const { snapshot, viewMode } = useDeployment();
  const technical = viewMode === "technical";
  const attention = snapshot.agents.filter((a) => needsAttention(a.status));
  const settled = snapshot.agents.filter((a) => !needsAttention(a.status));

  return (
    <section className="medha-panel animate-medha-in p-4" aria-label="Agent activity">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
          AGENT ACTIVITY
        </h2>
        <span className="text-[12px] text-medha-tertiary">
          {attention.length > 0 ? `${attention.length} need${attention.length === 1 ? "s" : ""} attention` : "all settled"}
        </span>
      </div>
      {snapshot.agents.length === 0 ? (
        <p className="text-[13px] text-medha-secondary">No agent activity recorded for this run.</p>
      ) : (
        <ul className="space-y-1">
          {[...attention, ...settled].map((agent) => (
            <li
              key={agent.id}
              className={cn(
                "rounded-medha-sm border px-2.5 py-1.5",
                needsAttention(agent.status)
                  ? agent.status === "failed"
                    ? "border-medha-danger/25 bg-medha-danger-soft/50"
                    : agent.status === "warning"
                      ? "border-medha-warning/25 bg-medha-warning-soft/50"
                      : "border-medha-run/25 bg-medha-run-soft/50"
                  : "border-medha-border bg-white",
              )}
            >
              <details>
                <summary className="cursor-pointer list-none [&::-webkit-details-marker]:hidden">
                  <span className="flex items-center gap-2 text-[12.5px]">
                    <span className={cn("status-dot", DOT[agent.status], agent.status === "running" && "medha-stage-pulse")} aria-hidden />
                    <span className="font-semibold text-medha-text">{agent.name}</span>
                    <span className="text-medha-tertiary">· {labelStatus(agent.status).toLowerCase()}</span>
                    {agent.durationMs ? (
                      <span className="text-medha-tertiary">· {(agent.durationMs / 1000).toFixed(1)}s</span>
                    ) : null}
                    <span className="min-w-0 flex-1 truncate text-medha-secondary">{agent.activity}</span>
                  </span>
                </summary>
                <div className="mt-1 border-t border-medha-border pt-1">
                  <p className="text-[12px] leading-relaxed text-medha-secondary">{agent.activity}</p>
                  <p className={cn("medha-mono mt-0.5 text-[12px] text-medha-tertiary", !technical && "truncate")}>
                    last: {agent.lastEvent}
                  </p>
                </div>
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
