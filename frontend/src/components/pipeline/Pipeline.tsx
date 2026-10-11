"use client";

import { useDeployment } from "@/context/DeploymentContext";
import { labelStatus, runSourceLabel, stageTone, statusGlyph } from "@/lib/ui/status";

export function Pipeline() {
  const { form, snapshot } = useDeployment();
  const source = runSourceLabel(form.mode, snapshot.isDemo);

  return (
    <section className="medha-panel animate-medha-in p-4 sm:p-5" aria-label="Deployment pipeline">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
          PIPELINE
        </h2>
        <span className="text-[11px] text-medha-tertiary">{source} progress</span>
      </div>
      <ol className="flex gap-2 overflow-x-auto pb-1">
        {snapshot.pipeline.map((stage, index) => (
          <li key={stage.id} className="flex min-w-[108px] flex-1 items-stretch gap-2">
            <div
              className={`flex w-full flex-col rounded-medha-sm border px-2.5 py-2 transition ${stageTone(stage.status)}`}
            >
              <div className="flex items-center gap-1.5">
                <span className="text-xs" aria-hidden>
                  {statusGlyph(stage.status)}
                </span>
                <span className="text-[11px] font-semibold tracking-wide">{stage.label}</span>
              </div>
              <p className="mt-1 text-[10px] leading-snug opacity-90">{stage.detail}</p>
              <p className="mt-auto pt-2 text-[10px] font-medium uppercase tracking-wide opacity-80">
                {labelStatus(stage.status)}
                {stage.durationMs ? ` · ${(stage.durationMs / 1000).toFixed(1)}s` : ""}
              </p>
            </div>
            {index < snapshot.pipeline.length - 1 ? (
              <span
                className="hidden self-center text-medha-tertiary sm:inline"
                aria-hidden
              >
                →
              </span>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
