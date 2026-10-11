"use client";

import { useMemo, useState } from "react";
import { useDeployment } from "@/context/DeploymentContext";
import { labelStatus, statusGlyph } from "@/lib/ui/status";
import type { ConstraintStatus } from "@/lib/demo/types";

type Filter = "all" | "conflicts" | "resolved" | "unresolved";

function matches(filter: Filter, status: ConstraintStatus): boolean {
  if (filter === "all") return true;
  if (filter === "conflicts") return status === "conflict";
  if (filter === "resolved")
    return status === "accepted" || status === "rejected" || status === "superseded";
  return status === "proposed" || status === "conflict";
}

export function ConstraintNegotiation() {
  const { snapshot, viewMode } = useDeployment();
  const [filter, setFilter] = useState<Filter>("all");
  const negotiation = snapshot.negotiation;
  const filtered = useMemo(
    () => snapshot.constraints.filter((c) => matches(filter, c.status)),
    [snapshot.constraints, filter],
  );

  return (
    <section className="medha-panel animate-medha-in p-4 sm:p-5">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
            CONSTRAINT NEGOTIATION
          </h2>
          <p className="mt-1 text-xs text-medha-secondary">
            Pre-execution CNP — research contribution #1
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {(["all", "conflicts", "resolved", "unresolved"] as Filter[]).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={`rounded-md px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide ${
                filter === f
                  ? "bg-medha-accent text-white"
                  : "bg-medha-surface-muted text-medha-secondary"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {!negotiation && snapshot.constraints.length === 0 ? (
        <p className="mt-4 rounded-md border border-medha-border bg-medha-surface text-medha-secondary py-3 text-center">
          No constraints yet. Start a DEMO deployment to see negotiation.
        </p>
      ) : (
        <>
          {negotiation ? (
            <div className="mt-4 rounded-md border border-medha-border bg-medha-surface-muted p-3">
              <p className="text-sm font-medium text-medha-text">{negotiation.conflictSummary}</p>
              <p className="mt-2 text-xs leading-relaxed text-medha-secondary">
                {viewMode === "simple"
                  ? negotiation.simpleExplanation
                  : (negotiation.technicalNotes ?? []).join(" · ") ||
                    negotiation.simpleExplanation}
              </p>
              <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <span className="text-xs font-medium text-medha-secondary">Round</span>
                <span className="text-xs font-semibold text-medha-text">{`${negotiation.round} / ${negotiation.maxRounds}`}</span>
                <span className="text-xs font-medium text-medha-secondary">Status</span>
                <span className="text-xs font-semibold text-medha-text">{negotiation.status.toUpperCase()}</span>
                <span className="text-xs font-medium text-medha-secondary">Resolution</span>
                <span className="text-xs font-semibold text-medha-text">{negotiation.resolution ?? "—"}</span>
                <span className="text-xs font-medium text-medha-secondary">Method</span>
                <span className="text-xs font-semibold text-medha-text">{negotiation.method ?? "—"}</span>
              </div>
            </div>
          ) : null}

          <ul className="mt-4 space-y-2">
            {filtered.length === 0 ? (
              <p className="mt-2 rounded-md border border-medha-border bg-medha-surface text-medha-secondary py-2 text-center">
                No constraints match this filter.
              </p>
            ) : (
              filtered.map((c) => (
                <li
                  key={c.id}
                  className="rounded-md border border-medha-border bg-medha-surface px-3 py-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs font-semibold tracking-wide text-medha-accent">{c.type}</p>
                    <p className="text-[9px] font-medium uppercase text-medha-secondary">
                      <span aria-hidden>{statusGlyph(c.status)} </span>
                      {labelStatus(c.status)}
                    </p>
                  </div>
                  <p className="mt-1 text-sm font-medium text-medha-text">{c.summary}</p>
                  <p className="mt-1 text-xs text-medha-secondary">{c.detail}</p>
                  <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[9px] text-medha-tertiary">
                    <span>{c.sourceAgent}</span>
                    <span>priority: {c.priority}</span>
                    {c.service ? <span>service: {c.service}</span> : null}
                    {viewMode === "technical" ? (
                      <span className="medha-mono">id={c.id}</span>
                    ) : null}
                  </div>
                  {viewMode === "technical" && c.technical ? (
                    <pre className="medha-mono mt-2 overflow-x-auto rounded bg-medha-surface p-2 text-[8px] text-medha-secondary">
                      {JSON.stringify(c.technical.payload, null, 2)}
                    </pre>
                  ) : null}
                </li>
              ))
            )}
          </ul>
        </>
      )}
    </section>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <p className="mt-4 rounded-md border border-medha-border bg-medha-surface py-3 text-center text-medha-secondary">
      {message}
    </p>
  );
}