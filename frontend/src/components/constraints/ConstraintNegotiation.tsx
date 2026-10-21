"use client";

import { useMemo, useState } from "react";
import { useDeployment } from "@/context/DeploymentContext";
import { labelStatus, statusGlyph } from "@/lib/ui/status";
import type { ConstraintStatus } from "@/lib/demo/types";
import { cn } from "@/lib/ui/cn";

type Filter = "all" | "conflicts" | "resolved" | "unresolved";

function matches(filter: Filter, status: ConstraintStatus): boolean {
  if (filter === "all") return true;
  if (filter === "conflicts") return status === "conflict";
  if (filter === "resolved")
    return status === "accepted" || status === "rejected" || status === "superseded";
  return status === "proposed" || status === "conflict";
}

function isResolved(status: ConstraintStatus): boolean {
  return status === "accepted" || status === "rejected" || status === "superseded";
}

/**
 * Consolidated CNP section: compact conflict counts, primary conflict with
 * resolution method and affected services, expandable constraint records.
 * Full negotiation history appears in Technical mode.
 */
export function ConstraintNegotiation() {
  const { snapshot, viewMode } = useDeployment();
  const [filter, setFilter] = useState<Filter>("all");
  const negotiation = snapshot.negotiation;
  const technical = viewMode === "technical";

  const counts = useMemo(() => {
    const total = snapshot.constraints.length;
    const conflicts = snapshot.constraints.filter((c) => c.status === "conflict").length;
    const resolved = snapshot.constraints.filter((c) => isResolved(c.status)).length;
    return { total, conflicts, resolved, unresolved: total - resolved };
  }, [snapshot.constraints]);

  const filtered = useMemo(
    () => snapshot.constraints.filter((c) => matches(filter, c.status)),
    [snapshot.constraints, filter],
  );

  const primary =
    snapshot.constraints.find((c) => c.status === "conflict") ??
    snapshot.constraints.find((c) => !isResolved(c.status)) ??
    null;
  // Older runs persist negotiation without involvedConstraintIds — never
  // assume backend optional arrays exist.
  const involvedIds = negotiation?.involvedConstraintIds ?? [];
  const affectedServices = useMemo(
    () => [...new Set(snapshot.constraints.map((c) => c.service).filter(Boolean))].slice(0, 4),
    [snapshot.constraints],
  );

  if (!negotiation && snapshot.constraints.length === 0) {
    return (
      <section className="medha-panel animate-medha-in p-4">
        <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
          CONFLICT RESOLUTION
        </h2>
        <p className="mt-2 text-sm text-medha-secondary">
          No constraint negotiation data for this run.
        </p>
      </section>
    );
  }

  return (
    <section className="medha-panel animate-medha-in p-4" aria-label="Conflict resolution">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
            CONFLICT RESOLUTION
          </h2>
          <p className="mt-1 text-[13px] text-medha-secondary">
            {counts.total} constraint{counts.total === 1 ? "" : "s"} · {counts.resolved} resolved
            {counts.unresolved > 0 ? (
              <span className="font-semibold text-medha-warning"> · {counts.unresolved} unresolved</span>
            ) : (
              " · none unresolved"
            )}
            {negotiation ? ` · round ${negotiation.round} / ${negotiation.maxRounds}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Constraint filter">
          {(["all", "conflicts", "resolved", "unresolved"] as Filter[]).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              aria-pressed={filter === f}
              className={cn(
                "rounded-md px-2 py-1 text-[12.5px] font-semibold uppercase tracking-wide transition",
                filter === f
                  ? "bg-medha-accent text-white"
                  : "bg-medha-surface-muted text-medha-secondary hover:text-medha-text",
              )}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {primary ? (
        <div
          className={cn(
            "mt-2.5 rounded-medha-sm border px-3 py-2",
            primary.status === "conflict"
              ? "border-medha-warning/30 bg-medha-warning-soft/50"
              : "border-medha-border bg-medha-muted/50",
          )}
        >
          <p className="text-[13px] font-semibold text-medha-text">
            <span aria-hidden>{statusGlyph(primary.status)} </span>
            {primary.summary}
          </p>
          <p className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[12.5px] text-medha-secondary">
            {negotiation?.method ? <span>Method: <span className="font-medium text-medha-text">{negotiation.method}</span></span> : null}
            {negotiation?.resolution ? <span>Resolution: <span className="font-medium text-medha-text">{negotiation.resolution}</span></span> : null}
            {affectedServices.length > 0 ? <span>Services: {affectedServices.join(", ")}</span> : null}
          </p>
        </div>
      ) : null}

      {technical && negotiation ? (
        <div className="mt-2.5 rounded-medha-sm border border-medha-border bg-white px-3 py-2">
          <p className="medha-label">
            Negotiation history
          </p>
          <p className="mt-1 text-[12.5px] leading-relaxed text-medha-secondary">
            {(negotiation.technicalNotes ?? []).join(" · ") || negotiation.simpleExplanation}
          </p>
          <p className="medha-mono mt-1 text-[12px] text-medha-tertiary">
            status={negotiation.status} · {involvedIds.length} involved constraint{involvedIds.length === 1 ? "" : "s"}
          </p>
        </div>
      ) : null}

      <ul className="mt-2 space-y-1">
        {filtered.length === 0 ? (
          <li className="rounded-medha-sm border border-medha-border px-3 py-2 text-center text-[13px] text-medha-secondary">
            No constraints match this filter.
          </li>
        ) : (
          filtered.map((c) => (
            <li key={c.id} className="rounded-medha-sm border border-medha-border bg-white">
              <details>
                <summary className="cursor-pointer list-none px-3 py-1.5 [&::-webkit-details-marker]:hidden">
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12.5px]">
                    <span className="font-semibold text-medha-accent">{c.type}</span>
                    <span className="min-w-0 flex-1 truncate font-medium text-medha-text">{c.summary}</span>
                    <span className="shrink-0 text-[12.5px] font-semibold uppercase text-medha-secondary">
                      <span aria-hidden>{statusGlyph(c.status)} </span>
                      {labelStatus(c.status)}
                    </span>
                  </span>
                </summary>
                <div className="border-t border-medha-border px-3 py-2">
                  <p className="text-[12.5px] text-medha-secondary">{c.detail}</p>
                  <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[12px] text-medha-tertiary">
                    <span className="medha-mono">{c.id}</span>
                    <span>{c.sourceAgent}</span>
                    <span>priority: {c.priority}</span>
                    {c.service ? <span>service: {c.service}</span> : null}
                  </p>
                  {technical && c.technical ? (
                    <pre className="medha-mono mt-1.5 overflow-x-auto rounded bg-medha-muted p-2 text-[12px] text-medha-secondary">
                      {JSON.stringify(c.technical.payload, null, 2)}
                    </pre>
                  ) : null}
                </div>
              </details>
            </li>
          ))
        )}
      </ul>
    </section>
  );
}
