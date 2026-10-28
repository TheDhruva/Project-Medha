"use client";

import { useEffect, useState } from "react";
import {
  fetchAssessmentSummary,
  type AssessmentSummary,
  type MergeDecision,
} from "@/lib/api/client";
import { Badge, Panel } from "@/components/ui/primitives";
import { severityTone } from "@/components/workspace/FindingsPanel";

function shortSha(sha: string | null): string {
  return sha ? sha.slice(0, 7) : "—";
}

const STATUS_TONE: Record<AssessmentSummary["status"], "success" | "warning" | "error" | "info" | "neutral"> = {
  completed: "success",
  partial: "warning",
  failed: "error",
  running: "info",
  never_assessed: "neutral",
  unknown: "neutral",
};

const MERGE_TONE: Record<MergeDecision["outcome"], "success" | "warning" | "error" | "neutral"> = {
  approved: "success",
  blocked: "error",
  pending: "warning",
  assessment_incomplete: "neutral",
};

const SEVERITIES = ["critical", "high", "medium", "low"] as const;

/**
 * Dashboard assessment block: scan coverage, merge decision, and blocking
 * findings from the project assessment-summary read model. Every value is
 * rendered from the response — missing data stays "—"/honest prose.
 */
export function AssessmentPanel({ projectId, runKey }: { projectId: string; runKey: string | null }) {
  const [data, setData] = useState<AssessmentSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAssessmentSummary(projectId)
      .then((value) => {
        if (!cancelled) setData(value);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setData(null);
          setError(err instanceof Error ? err.message : "Assessment summary is unavailable.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, runKey, reload]);

  if (loading) {
    return (
      <Panel title="Assessment">
        <p className="text-[13.5px] text-medha-secondary" aria-live="polite">
          Loading assessment…
        </p>
      </Panel>
    );
  }

  if (error) {
    return (
      <Panel title="Assessment">
        <div role="alert" className="rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-[13px]">
          <p className="font-semibold text-medha-danger">Assessment summary is unavailable: {error}</p>
          <button
            type="button"
            onClick={() => setReload((n) => n + 1)}
            className="mt-2 rounded border border-medha-danger/30 bg-white px-2.5 py-1 text-[12.5px] font-semibold text-medha-danger hover:bg-medha-danger-soft"
          >
            Retry
          </button>
        </div>
      </Panel>
    );
  }

  if (!data) return null;

  const latest = data.latest_assessment;
  const gaps = latest?.coverage.gaps ?? [];
  const merge = data.merge;
  const prNumber = data.pull_request?.number ?? merge?.pull_request?.number ?? null;
  const setupNeeded =
    !data.setup.webhook_secret_configured || data.setup.status_checks === "setup_required";
  // Prefer an actionable reason; approved decisions surface their info note.
  const primaryReason = merge
    ? merge.reasons.find((r) => r.kind === "blocking" || r.kind === "pending") ??
      (merge.outcome === "approved" ? merge.reasons.find((r) => r.kind === "info") ?? null : null)
    : null;

  return (
    <Panel title="Assessment" eyebrow={data.branch}>
      <div className="divide-y divide-medha-border">
        {/* Scan: recorded coverage status, revisions, and gaps. */}
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 pb-2.5">
          <Badge tone={STATUS_TONE[data.status]}>{data.status.replace(/_/g, " ")}</Badge>
          {latest ? (
            <>
              <span className="medha-mono text-[12px] text-medha-tertiary">
                commit {shortSha(latest.commit_sha)} · base {shortSha(latest.base_sha)}
              </span>
              <Badge tone={gaps.length > 0 ? "warning" : latest.coverage.security_scan ? "success" : "neutral"}>
                scan {latest.coverage.security_scan ?? "—"}
              </Badge>
              {gaps.length > 0 ? (
                <span className="text-[12.5px] text-medha-warning">
                  {gaps.length} coverage gap{gaps.length === 1 ? "" : "s"}: {gaps.join(" · ")}
                </span>
              ) : (
                <span className="text-[12.5px] text-medha-tertiary">no coverage gaps recorded</span>
              )}
              {latest.is_demo ? (
                <span className="text-[12px] font-semibold text-medha-tertiary">DEMO/MOCK</span>
              ) : null}
            </>
          ) : (
            <span className="text-[12.5px] text-medha-secondary">
              No assessment recorded for this project yet.
            </span>
          )}
        </div>

        {/* Merge: advisory decision with its first actionable reason. */}
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 py-2.5">
          {merge ? (
            <>
              <Badge tone={MERGE_TONE[merge.outcome]}>{merge.outcome.replace(/_/g, " ")}</Badge>
              <Badge tone="neutral">advisory</Badge>
              <span className="medha-mono text-[12px] text-medha-tertiary">
                {shortSha(merge.assessed.base_sha)} → {shortSha(merge.assessed.head_sha)}
              </span>
              {prNumber != null ? (
                <span className="text-[12.5px] text-medha-secondary">PR #{prNumber}</span>
              ) : null}
              {primaryReason ? (
                <span className="min-w-0 text-[12.5px] text-medha-secondary">{primaryReason.message}</span>
              ) : null}
              {merge.outcome !== "approved" && merge.next_actions[0] ? (
                <span className="text-[12.5px] text-medha-tertiary">Next: {merge.next_actions[0]}</span>
              ) : null}
            </>
          ) : (
            <span className="text-[12.5px] text-medha-secondary">No merge decision recorded.</span>
          )}
        </div>

        {/* Findings: recorded counts, severity chips, blocking top five. */}
        <div className="py-2.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-[13px] font-medium text-medha-text">
              {data.findings.total} finding{data.findings.total === 1 ? "" : "s"} ·{" "}
              {data.findings.unresolved} unresolved · {data.findings.new_since_baseline} new since baseline
            </span>
            {SEVERITIES.map((s) => (
              <Badge key={s} tone={severityTone(s)}>
                {s} {data.findings.by_severity[s]}
              </Badge>
            ))}
          </div>
          {data.blocking_findings.length > 0 ? (
            <ul className="mt-1.5 space-y-1">
              {data.blocking_findings.map((finding) => (
                <li key={finding.finding_id} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[12.5px]">
                  <Badge tone={severityTone(finding.severity)}>{finding.severity}</Badge>
                  <span className="medha-mono font-medium text-medha-text">
                    {finding.rule_id || finding.source || "—"}
                  </span>
                  <span className="min-w-0 max-w-[420px] flex-1 truncate text-medha-secondary" title={finding.message}>
                    {finding.message}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1.5 text-[12.5px] text-medha-tertiary">No blocking findings recorded.</p>
          )}
        </div>

        {/* Setup gate: stated neutrally with the backend's own note. */}
        {setupNeeded ? (
          <div className="mt-2.5 rounded-lg border border-medha-border bg-medha-surface-muted px-3 py-2">
            <p className="text-[12.5px] font-semibold text-medha-secondary">GitHub setup incomplete</p>
            <p className="mt-0.5 text-[12px] leading-relaxed text-medha-tertiary">{data.setup.note}</p>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
