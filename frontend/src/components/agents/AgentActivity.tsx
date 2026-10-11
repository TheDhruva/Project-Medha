"use client";

import { useDeployment } from "@/context/DeploymentContext";
import { labelStatus, statusGlyph } from "@/lib/ui/status";
import type { AgentStatus } from "@/lib/demo/types";

function agentTone(status: AgentStatus): string {
  switch (status) {
    case "running":
      return "border-medha-accent/30 bg-medha-accent-soft/40";
    case "complete":
      return "border-medha-success/25 bg-medha-success-soft/50";
    case "warning":
      return "border-medha-warning/25 bg-medha-warning-soft/50";
    case "failed":
      return "border-medha-danger/25 bg-medha-danger-soft/50";
    case "skipped":
      return "border-medha-border bg-medha-muted/40";
    default:
      return "border-medha-border bg-white";
  }
}

export function AgentActivity() {
  const { snapshot, viewMode } = useDeployment();

  return (
    <section className="medha-panel animate-medha-in p-4 sm:p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
          AGENT ACTIVITY
        </h2>
        <span className="text-[11px] text-medha-tertiary">10 logical agents</span>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        {snapshot.agents.map((agent) => (
          <li
            key={agent.id}
            className={`rounded-medha-sm border px-3 py-2.5 transition ${agentTone(agent.status)}`}
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="text-sm font-semibold text-medha-text">{agent.name}</p>
                <p className="mt-0.5 text-[11px] font-medium uppercase tracking-wide text-medha-secondary">
                  <span aria-hidden>{statusGlyph(agent.status)} </span>
                  {labelStatus(agent.status)}
                  {agent.durationMs ? ` · ${(agent.durationMs / 1000).toFixed(1)}s` : ""}
                </p>
              </div>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-medha-secondary">{agent.activity}</p>
            {viewMode === "technical" ? (
              <p className="medha-mono mt-1 text-[10px] text-medha-tertiary">
                last={agent.lastEvent}
              </p>
            ) : (
              <p className="mt-1 text-[11px] text-medha-tertiary">Last: {agent.lastEvent}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
