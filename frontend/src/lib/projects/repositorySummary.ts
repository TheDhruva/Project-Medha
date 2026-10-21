import type { RepositorySummary, RunSummary } from "@/lib/api/client";

export interface RepositorySummarySelection {
  summary: RepositorySummary | null;
  revision: string | null;
  stale: boolean;
}

function usable(summary: RepositorySummary | undefined): summary is RepositorySummary & { text: string } {
  return (
    !!summary &&
    (summary.status === "available" || summary.status === "stale") &&
    typeof summary.text === "string" &&
    summary.text.trim().length > 0
  );
}

/** Prefer the newest usable summary; mark it stale when it is not for the
 * latest analyzed revision. During a newer run, the prior summary stays. */
export function selectRepositorySummary(runs: RunSummary[]): RepositorySummarySelection {
  const latest = runs[0] ?? null;
  const found = runs.find((run) => usable(run.repository_summary));
  if (!found || !usable(found.repository_summary)) {
    return { summary: null, revision: null, stale: false };
  }
  const summary = found.repository_summary;
  const revision = summary.commit_sha ?? found.target_revision ?? null;
  const latestRevision = latest?.target_revision ?? null;
  const stale =
    summary.status === "stale" ||
    Boolean(revision && latestRevision && revision !== latestRevision);
  return { summary, revision, stale };
}
