import type { RunSummary } from "@/lib/api/client";

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

/** Human-readable run title. Prefers the repository name; never fabricates. */
export function scenarioDisplayName(run: Pick<RunSummary, "scenario" | "repository_url" | "label">): string {
  if (run.label === "DEMO/MOCK" && run.scenario) {
    return String(run.scenario)
      .toLowerCase()
      .split("_")
      .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
      .join(" ");
  }
  if (run.label) return run.label;
  return shortRepo(run.repository_url);
}
