"use client";

import { useDeployment } from "@/context/DeploymentContext";

export function ViewModeToggle() {
  const { viewMode, setViewMode } = useDeployment();

  return (
    <div
      className="inline-flex rounded-medha-sm border border-medha-border bg-white p-1"
      role="group"
      aria-label="Explanation detail"
    >
      {(["simple", "technical"] as const).map((mode) => {
        const active = viewMode === mode;
        return (
          <button
            key={mode}
            type="button"
            onClick={() => setViewMode(mode)}
            aria-pressed={active}
            className={`rounded-[6px] px-3 py-1.5 text-xs font-semibold uppercase tracking-wide transition ${
              active
                ? "bg-medha-accent text-white"
                : "text-medha-secondary hover:text-medha-text"
            }`}
          >
            {mode}
          </button>
        );
      })}
    </div>
  );
}
