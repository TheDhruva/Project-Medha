"use client";

import { useDeployment } from "@/context/DeploymentContext";
import { ViewModeToggle } from "./ViewModeToggle";

export function WhatMedhaIsDoing({ showToggle = true }: { showToggle?: boolean }) {
  const { snapshot, viewMode } = useDeployment();
  const { explain } = snapshot;
  const text = viewMode === "simple" ? explain.simpleText : explain.technicalText;

  return (
    <section className="medha-panel animate-medha-in overflow-hidden border-medha-accent/20">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-medha-border bg-medha-accent-soft/50 px-5 py-3">
        <h2 className="font-display text-sm font-semibold tracking-wide text-medha-accent-hover">
          WHAT MEDHA IS DOING
        </h2>
        {showToggle ? <ViewModeToggle /> : null}
      </div>
      <div className="px-5 py-4">
        <p className="text-[15px] leading-relaxed text-medha-text">{text}</p>
        <dl className="mt-4 grid gap-3 sm:grid-cols-3">
          <Meta label="Current stage" value={explain.currentStage ?? "—"} />
          <Meta
            label="Round"
            value={explain.round != null ? `${explain.round} / 3` : "—"}
          />
          <Meta label="Status" value={explain.statusLabel} />
        </dl>
        <p className="mt-3 text-[12px] text-medha-tertiary">
          Observable system events only — no fabricated chain-of-thought.
        </p>
      </div>
    </section>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-medha-sm border border-medha-border bg-medha-muted/60 px-3 py-2">
      <dt className="medha-label">{label}</dt>
      <dd className="mt-1 font-display text-sm font-semibold text-medha-text">{value}</dd>
    </div>
  );
}
