"use client";

import { useDeployment } from "@/context/DeploymentContext";

export function DeploymentResult() {
  const { snapshot, viewMode } = useDeployment();
  const result = snapshot.result;

  if (!result) {
    return (
      <section className="medha-panel animate-medha-in p-4 sm:p-5">
        <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
          DEPLOYMENT RESULT
        </h2>
        <p className="mt-3 rounded-medha-sm border border-dashed border-medha-border bg-medha-muted/40 px-3 py-8 text-center text-sm text-medha-secondary">
          No result yet. Run a DEMO scenario to see success, failure, or partial recovery.
        </p>
      </section>
    );
  }

  const tone =
    result.kind === "success"
      ? "border-medha-success/30 bg-medha-success-soft"
      : result.kind === "partial_recovery"
        ? "border-medha-warning/30 bg-medha-warning-soft"
        : "border-medha-danger/30 bg-medha-danger-soft";

  const titleColor =
    result.kind === "success"
      ? "text-medha-success"
      : result.kind === "partial_recovery"
        ? "text-medha-warning"
        : "text-medha-danger";

  return (
    <section className={`medha-panel animate-medha-in overflow-hidden border ${tone}`}>
      <div className="px-5 py-4">
        <p className="medha-label">
          Deployment result
          {snapshot.isDemo ? " · DEMO" : " · LIVE"}
        </p>
        <h2 className={`mt-1 font-display text-2xl font-semibold ${titleColor}`}>
          {result.title}
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-medha-text">{result.message}</p>

        <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Stat label="Status" value={result.title} />
          <Stat label="Duration" value={result.durationLabel} />
          <Stat label="Services" value={result.servicesLabel} />
          <Stat
            label="Verification / critic"
            value={
              result.verificationScore != null && result.verificationScore > 0
                ? `${result.verificationScore} / 100`
                : "Not evaluated yet"
            }
          />
          <Stat
            label="Constraints resolved"
            value={String(result.constraintsResolved)}
          />
          <Stat
            label="Rollback scope"
            value={result.rollbackScope ?? "None"}
            mono={viewMode === "technical" && !!result.rollbackScope}
          />
        </dl>
      </div>
    </section>
  );
}

function Stat({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="rounded-medha-sm border border-white/70 bg-white/70 px-3 py-2">
      <dt className="medha-label">{label}</dt>
      <dd className={`mt-1 text-sm font-semibold text-medha-text ${mono ? "medha-mono text-xs" : ""}`}>
        {value}
      </dd>
    </div>
  );
}
