import type { RunSummary } from "@/lib/api/client";
import type { ScenarioId } from "@/lib/demo/types";
import { scenarioById } from "@/lib/demo/scenarios";

const SCENARIO_FALLBACK: Record<string, string> = {
  SUCCESSFUL_DEPLOYMENT: "Configuration Change",
};

function shortRepo(url: string): string {
  if (!url) return "Repository change";
  try {
    const withoutProtocol = url.replace(/^https?:\/\//, "").replace(/^git@/, "");
    const parts = withoutProtocol.split("/").filter(Boolean);
    if (parts.length === 0) return url;
    const last = parts[parts.length - 1].replace(/\.git$/, "");
    return last
      .split(/[-_]/)
      .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
      .join(" ");
  } catch {
    return url;
  }
}

/** Human-readable run title. Prefers the demo scenario name; falls back to repo. */
export function scenarioDisplayName(run: Pick<RunSummary, "scenario" | "repository_url" | "label">): string {
  const scenario = run.scenario as ScenarioId | null;
  if (scenario) {
    try {
      return scenarioById(scenario).name;
    } catch {
      if (SCENARIO_FALLBACK[scenario]) return SCENARIO_FALLBACK[scenario];
    }
    if (SCENARIO_FALLBACK[scenario]) return SCENARIO_FALLBACK[scenario];
    return scenario
      .toLowerCase()
      .split("_")
      .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
      .join(" ");
  }
  if (run.label) return run.label;
  return shortRepo(run.repository_url);
}
