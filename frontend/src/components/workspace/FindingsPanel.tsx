"use client";

import { Fragment, useEffect, useState } from "react";
import {
  fetchProjectFindings,
  type FindingView,
  type ProjectFindingsResponse,
} from "@/lib/api/client";
import { Badge } from "@/components/ui/primitives";

/* Severity chip tone (shared with the assessment block): critical → red,
   high → amber, medium → blue, low/unrecognized → neutral grey. */
export function severityTone(severity: string): "error" | "warning" | "info" | "neutral" {
  switch (severity.toLowerCase()) {
    case "critical":
      return "error";
    case "high":
      return "warning";
    case "medium":
      return "info";
    default:
      return "neutral";
  }
}

const SEVERITIES = ["critical", "high", "medium", "low"] as const;
const SORTS = [
  { id: "severity", label: "Severity" },
  { id: "last_seen", label: "Last seen" },
  { id: "first_seen", label: "First seen" },
] as const;

const SELECT_CLASS =
  "rounded-lg border border-medha-border bg-white px-3 py-1.5 text-sm text-medha-text";

/** Short displayed form of one evidence/history entry — recorded fields only. */
function entryText(entry: unknown): string {
  if (entry == null) return "";
  if (typeof entry === "string") return entry;
  if (typeof entry === "object" && !Array.isArray(entry)) {
    const record = entry as Record<string, unknown>;
    const parts = Object.entries(record)
      .filter(([, value]) => value == null || ["string", "number", "boolean"].includes(typeof value))
      .map(([key, value]) => `${key}: ${value == null ? "—" : String(value)}`);
    return parts.length > 0 ? parts.join(" · ") : JSON.stringify(entry);
  }
  return String(entry);
}

function shortSha(sha: string | null): string {
  return sha ? sha.slice(0, 7) : "—";
}

function FindingRow({ finding }: { finding: FindingView }) {
  const location = finding.path
    ? `${finding.path}${finding.line != null ? `:${finding.line}` : ""}`
    : null;
  const evidence = finding.evidence.slice(-3);
  const history = finding.history.slice(-5);
  return (
    <li className="py-2.5 first:pt-0 last:pb-0">
      <details>
        <summary className="flex cursor-pointer flex-wrap items-center gap-x-2 gap-y-1 rounded text-[12.5px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent [&::-webkit-details-marker]:hidden">
          <Badge tone={severityTone(finding.severity)}>{finding.severity}</Badge>
          <Badge tone="neutral">{finding.status.replace(/_/g, " ")}</Badge>
          {finding.category ? (
            <span className="text-medha-secondary">{finding.category}</span>
          ) : null}
          <span className="medha-mono font-medium text-medha-text">
            {finding.rule_id || finding.source || "—"}
          </span>
          {location ? (
            <span className="medha-mono text-medha-tertiary">{location}</span>
          ) : null}
          {finding.confidence ? (
            <span className="text-medha-tertiary">{finding.confidence}</span>
          ) : null}
          <span className="min-w-0 max-w-[320px] flex-1 truncate text-medha-text" title={finding.message}>
            {finding.message}
          </span>
          <span className="medha-mono shrink-0 text-[11px] text-medha-tertiary">
            {shortSha(finding.first_seen_sha)} → {shortSha(finding.last_seen_sha)}
          </span>
          {finding.blocks_merge ? <Badge tone="error">blocks merge</Badge> : null}
        </summary>
        <dl className="mt-1.5 space-y-1 rounded-lg border border-medha-border bg-medha-surface-muted px-2.5 py-2 text-[12.5px]">
          {finding.explanation ? (
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-medha-tertiary">Explanation</dt>
              <dd className="min-w-0 text-medha-secondary">{finding.explanation}</dd>
            </div>
          ) : null}
          {finding.remediation ? (
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-medha-tertiary">Remediation</dt>
              <dd className="min-w-0 text-medha-secondary">{finding.remediation}</dd>
            </div>
          ) : null}
          {evidence.length > 0 ? (
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-medha-tertiary">Evidence</dt>
              <dd className="min-w-0 space-y-0.5">
                {evidence.map((entry, i) => (
                  <p key={i} className="medha-mono break-words text-[11.5px] text-medha-secondary">
                    {entryText(entry)}
                  </p>
                ))}
              </dd>
            </div>
          ) : null}
          {history.length > 0 ? (
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-medha-tertiary">History</dt>
              <dd className="min-w-0 space-y-0.5">
                {history.map((entry, i) => (
                  <p key={i} className="medha-mono break-words text-[11.5px] text-medha-secondary">
                    {entryText(entry)}
                  </p>
                ))}
              </dd>
            </div>
          ) : null}
          {!finding.explanation && !finding.remediation && evidence.length === 0 && history.length === 0 ? (
            <p className="text-medha-tertiary">No further detail recorded for this finding.</p>
          ) : null}
        </dl>
      </details>
    </li>
  );
}

/** Focused findings view with server-side severity/lifecycle/sort filters. */
export function FindingsPanel({ projectId }: { projectId: string }) {
  const [severity, setSeverity] = useState<string>("all");
  const [status, setStatus] = useState<string>("all");
  const [sort, setSort] = useState<string>("severity");
  const [data, setData] = useState<ProjectFindingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchProjectFindings(projectId, {
      status: status === "all" ? undefined : status,
      severity: severity === "all" ? undefined : severity,
      sort,
    })
      .then((response) => {
        if (!cancelled) setData(response);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setData(null);
          setError(err instanceof Error ? err.message : "Findings are unavailable.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, severity, status, sort, reload]);

  const lifecycleOptions = data?.lifecycle_states ?? [];
  const counts = data
    ? [
        ...Object.entries(data.severity_counts).map(([key, value]) => `${key} ${value}`),
        ...Object.entries(data.status_counts).map(([key, value]) => `${key.replace(/_/g, " ")} ${value}`),
      ].join(" · ")
    : null;

  return (
    <div className="mt-3 border-t border-medha-border pt-3">
      <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
        <label htmlFor="findings-severity" className="medha-label">Severity</label>
        <select
          id="findings-severity"
          value={severity}
          onChange={(e) => setSeverity(e.target.value)}
          className={SELECT_CLASS}
        >
          <option value="all">All severities</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <label htmlFor="findings-lifecycle" className="medha-label">Status</label>
        <select
          id="findings-lifecycle"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className={SELECT_CLASS}
        >
          <option value="all">All statuses</option>
          {lifecycleOptions.map((s) => (
            <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
          ))}
        </select>

        <label htmlFor="findings-sort" className="medha-label">Sort</label>
        <select
          id="findings-sort"
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          className={SELECT_CLASS}
        >
          {SORTS.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>

        {data && !loading && !error ? (
          <p className="text-[12.5px] text-medha-tertiary" aria-live="polite">
            {data.total} finding{data.total === 1 ? "" : "s"} total
            {counts ? ` · ${counts}` : ""}
          </p>
        ) : null}
      </div>

      {loading ? (
        <p className="mt-3 text-[13.5px] text-medha-secondary" aria-live="polite">Loading findings…</p>
      ) : error ? (
        <div role="alert" className="mt-3 rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-[13px]">
          <p className="font-semibold text-medha-danger">Findings are unavailable: {error}</p>
          <button
            type="button"
            onClick={() => setReload((n) => n + 1)}
            className="mt-2 rounded border border-medha-danger/30 bg-white px-2.5 py-1 text-[12.5px] font-semibold text-medha-danger hover:bg-medha-danger-soft"
          >
            Retry
          </button>
        </div>
      ) : !data || data.findings.length === 0 ? (
        <p className="mt-3 text-[13px] text-medha-secondary">
          No findings recorded for this repository.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-medha-border border-t border-medha-border">
          {data.findings.map((finding) => (
            <FindingRow key={finding.finding_id} finding={finding} />
          ))}
        </ul>
      )}
    </div>
  );
}
