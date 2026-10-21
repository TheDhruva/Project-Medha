"use client";

import { useDeployment } from "@/context/DeploymentContext";
import { labelStatus, runSourceLabel, stageTone, statusGlyph } from "@/lib/ui/status";
import { cn } from "@/lib/ui/cn";

/**
 * Compact responsive pipeline stepper. Same persisted stage states as
 * before — wraps to the content width instead of scrolling horizontally.
 * Stage errors live in the diagnosis card, not here.
 */
export function Pipeline() {
  const { form, snapshot } = useDeployment();
  const source = runSourceLabel(form.mode, snapshot.isDemo);

  return (
    <section className="medha-panel animate-medha-in p-4" aria-label="Deployment pipeline">
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
          PIPELINE
        </h2>
        <span className="text-[12px] text-medha-tertiary">{source} progress</span>
      </div>
      <ol className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-4">
        {snapshot.pipeline.map((stage) => (
          <li
            key={stage.id}
            aria-current={stage.status === "running" ? "step" : undefined}
            className={cn(
              "rounded-medha-sm border px-2.5 py-1.5 transition",
              stageTone(stage.status),
            )}
            title={stage.detail || undefined}
          >
            <p className="flex items-center gap-1.5 text-[12px] font-semibold">
              <span
                aria-hidden
                className={cn(stage.status === "running" && "medha-stage-pulse")}
              >
                {statusGlyph(stage.status)}
              </span>
              <span className="truncate">{stage.label}</span>
            </p>
            <p className="mt-0.5 truncate text-[12px] opacity-80">
              {labelStatus(stage.status)}
              {stage.durationMs ? ` · ${(stage.durationMs / 1000).toFixed(1)}s` : ""}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
