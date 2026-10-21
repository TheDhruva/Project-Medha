/**
 * Project dashboard derivations: scorecards + findings.
 *
 * Every value comes from a stored artifact or API response. Missing evidence
 * yields null ("Not assessed") — never a fabricated 0 or 100.
 */
import type {
  ExecutionReadiness,
  ProductScore,
  RunSummary,
  ScoresResponse,
} from "@/lib/api/client";
import type { VerificationSummary } from "./useProjectData";
import { CONFIG_BLOCK_CODES } from "./useProjectData";
import { isRunningStatus } from "./projects";


/* ------------------------------- scorecards -------------------------------- */

export type ScorecardStatus = "healthy" | "warning" | "critical" | "not_assessed" | "stale";

export interface ScorecardMetric {
  id: "code-quality" | "security" | "verification" | "readiness";
  title: string;
  /** 0-100, or null when the run has no evidence for this metric. */
  value: number | null;
  /** Short evidence line; also the "why" when value is null. */
  evidence: string;
  /** Backend assessment state, rendered as text (never colour alone). */
  status: ScorecardStatus;
  statusLabel: string;
  /** Assessed / applicable check counts for this category. */
  coverage: { assessed: number; applicable: number } | null;
  assessedAt: string | null;
  /** Short source revision the score was computed against, when known. */
  revision: string | null;
  /** True when the score revision no longer matches the selected run. */
  stale: boolean;
  /** True while a newer analysis is running for this project. */
  refreshing: boolean;
  isDemo: boolean;
  /** Link to the artifact detail page backing this metric. */
  href: string;
}

/** Gauge/status color band. Never color-only: the value is always rendered. */
export function scoreTone(value: number | null): "success" | "warning" | "danger" | "neutral" {
  if (value == null) return "neutral";
  if (value >= 85) return "success";
  if (value >= 60) return "warning";
  return "danger";
}

const STATUS_LABELS: Record<ScorecardStatus, string> = {
  healthy: "Assessed",
  warning: "Needs attention",
  critical: "Critical findings",
  not_assessed: "Not assessed",
  stale: "Stale assessment",
};

function checkStatus(value: unknown): string {
  return typeof value === "string" ? value.toLowerCase() : "";
}

function severityRank(value: unknown): number {
  return { critical: 5, high: 4, medium: 3, low: 2, info: 1 }[
    typeof value === "string" ? value.toLowerCase() : ""
  ] ?? 0;
}

function assessedChecks(evidence: Record<string, unknown> | null) {
  const raw = evidence?.checks;
  return Array.isArray(raw)
    ? raw
        .map(asRecord)
        .filter((c): c is Record<string, unknown> => c !== null)
        .filter((c) => ["passed", "failed", "warning"].includes(checkStatus(c.status)))
    : [];
}

function coverageOf(evidence: Record<string, unknown> | null): { assessed: number; applicable: number } | null {
  const cov = asRecord(evidence?.coverage);
  const assessed = asNumber(cov?.assessed);
  const applicable = asNumber(cov?.applicable);
  return assessed != null && applicable != null ? { assessed, applicable } : null;
}

function evidenceLine(score: ProductScore | undefined): string {
  if (!score) return "No score snapshot recorded for this run.";
  const ev = asRecord(score.evidence) ?? {};
  if (score.value == null) {
    const reason = typeof ev.reason === "string" ? ev.reason : "no assessment evidence";
    return `Not assessed: ${reason}.`;
  }
  if (typeof ev.top_finding === "string" && ev.top_finding.trim()) return ev.top_finding;
  const checks = assessedChecks(ev);
  const failed = checks.filter((c) => checkStatus(c.status) === "failed");
  if (failed.length > 0) {
    return `${failed.length} failed check${failed.length === 1 ? "" : "s"} reduced this score`;
  }
  const warned = checks.filter((c) => checkStatus(c.status) === "warning").length;
  if (warned > 0) return `${warned} warning${warned === 1 ? "" : "s"} reduced this score`;
  if (checks.length > 0) {
    return `All ${checks.length} assessed check${checks.length === 1 ? "" : "s"} passed`;
  }
  return "Evidence-backed score.";
}

function statusOf(
  value: number | null,
  evidence: Record<string, unknown> | null,
  stale: boolean,
): ScorecardStatus {
  if (stale) return "stale";
  if (value == null) return "not_assessed";
  const checks = assessedChecks(evidence);
  const highFailure = checks.some(
    (c) => checkStatus(c.status) === "failed" && severityRank(c.severity) >= 4,
  );
  if (highFailure || value < 60) return "critical";
  if (value < 85 || checks.some((c) => checkStatus(c.status) !== "passed")) return "warning";
  return "healthy";
}

function revisionsMatch(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return true;
  const normalize = (v: string) => v.replace(/[^0-9a-z]/gi, "").toLowerCase();
  const left = normalize(a);
  const right = normalize(b);
  return left.startsWith(right) || right.startsWith(left);
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function shortSha(value: string | null | undefined): string | null {
  if (!value) return null;
  return value.length > 12 ? value.slice(0, 8) : value;
}

export function deriveScorecards(input: {
  run: RunSummary;
  /** Kept for API compatibility; scores are backend-owned and authoritative. */
  verification?: Record<string, unknown> | null;
  /** Kept for API compatibility; critic output never supplies numeric scores. */
  critic?: Record<string, unknown> | null;
  scores: ScoresResponse | null;
  projectId: string;
}): ScorecardMetric[] {
  const { run, scores, projectId } = input;
  const isDemo = run.is_demo;
  const runRevision = shortSha(run.target_revision);
  const verificationHref = `/projects/${projectId}/verification?run=${encodeURIComponent(run.deployment_id)}`;

  const make = (
    id: ScorecardMetric["id"],
    title: string,
    score: ProductScore | undefined,
    href: string,
  ): ScorecardMetric => {
    const evidence = asRecord(score?.evidence);
    const stale =
      (scores != null && scores.deployment_id !== run.deployment_id) ||
      !revisionsMatch(score?.target_sha, run.target_revision);
    const value = score?.value ?? null;
    const status = statusOf(value, evidence, stale);
    return {
      id,
      title,
      value,
      evidence: evidenceLine(score),
      status,
      statusLabel: STATUS_LABELS[status],
      coverage: coverageOf(evidence),
      assessedAt: score?.computed_at ?? null,
      revision: shortSha(score?.target_sha) ?? runRevision,
      stale,
      refreshing: isRunningStatus(run.status),
      isDemo,
      href,
    };
  };

  return [
    make("code-quality", "Code Quality", scores?.scores?.code_quality, verificationHref),
    make("security", "Security Posture", scores?.scores?.security, verificationHref),
    make(
      "verification",
      "Verification Confidence",
      scores?.scores?.verification_confidence,
      verificationHref,
    ),
    make(
      "readiness",
      "Deployment Readiness",
      scores?.scores?.deployment_readiness,
      `/projects/${projectId}/runs/${run.deployment_id}`,
    ),
  ];
}

/* --------------------------------- findings -------------------------------- */

export interface Finding {
  id: string;
  tone: "error" | "warning" | "info";
  title: string;
  body: string;
  action?: { label: string; href: string };
  /** Operator/developer guidance (backend process/env), shown as a hint line. */
  note?: string;
  /** Bulleted next actions from the readiness contract, when present. */
  nextActions?: string[];
}

/** Failure codes that mean "the run needs a deployment target configured". */
const TARGET_ERROR_CODES = new Set([
  "MULTIPLE_APPS_REQUIRE_TARGET",
  "INVALID_DEPLOYMENT_TARGET",
  "AMBIGUOUS_DEPLOY_TARGET",
  "DEPLOYMENT_UNSUPPORTED",
  "NO_TARGET_CANDIDATES",
  "PLAN_REQUIRES_REVIEW",
]);

/** Failure codes that mean "execution was never configured/available". */

export function deriveFindings(input: {
  run: RunSummary | null;
  readiness: ExecutionReadiness | null;
  verification: VerificationSummary | null;
  securityFailures: number | null;
  conflicts: number;
  negotiationResolved: boolean;
  pendingApprovals: number;
  projectId: string;
}): Finding[] {
  const {
    run,
    readiness,
    verification,
    securityFailures,
    conflicts,
    negotiationResolved,
    pendingApprovals,
    projectId,
  } = input;
  const findings: Finding[] = [];
  const errorCode = run?.error_code ?? null;
  const failed = run?.status === "failed";

  let rootCauseShown = false;

  if (failed && errorCode && TARGET_ERROR_CODES.has(errorCode)) {
    rootCauseShown = true;
    findings.push({
      id: "target-required",
      tone: "error",
      title: "Deployment target required",
      body:
        run?.error_summary ||
        "This run stopped because no deployment target could be selected for the repository.",
      action: { label: "Choose target in project settings →", href: `/projects/${projectId}/settings` },
    });
  }

  if (failed && verification?.passed === false) {
    rootCauseShown = true;
    findings.push({
      id: "verification-failed",
      tone: "error",
      title: "Verification gate failed",
      body:
        verification.blocking[0] ??
        verification.summary ??
        "One or more verification checks failed for this run; execution is blocked until they pass.",
      action: { label: "Open verification details →", href: `/projects/${projectId}/verification` },
    });
  }

  if (readiness && readiness.status !== "ready") {
    const sameCause = failed && errorCode != null && CONFIG_BLOCK_CODES.has(errorCode);
    findings.push({
      id: "execution-blocked",
      tone: "error",
      title:
        readiness.status === "disabled" ? "Execution disabled for this environment" : "Execution blocked",
      body:
        readiness.message +
        (sameCause
          ? " Analysis and verification results from this run remain valid."
          : ""),
      action: { label: "Execution settings →", href: "/settings" },
      note: [
        readiness.requires_operator ? "Backend/operator action required" : null,
        readiness.restart_required ? "backend restart required" : null,
      ]
        .filter(Boolean)
        .join(" · ") || undefined,
      nextActions: readiness.next_actions?.slice(0, 3),
    });
  }

  if (typeof securityFailures === "number" && securityFailures > 0) {
    findings.push({
      id: "security-failures",
      tone: "warning",
      title: "Security findings need attention",
      body: `${securityFailures} security check${securityFailures === 1 ? "" : "s"} failed for this run.`,
      action: { label: "Review security checks →", href: `/projects/${projectId}/verification` },
    });
  }

  if (failed && !rootCauseShown && run?.error_summary) {
    findings.push({
      id: "run-failed",
      tone: "warning",
      title: "Selected run failed",
      body: run.error_summary,
      action: {
        label: "Open run detail →",
        href: `/projects/${projectId}/runs/${run.deployment_id}`,
      },
    });
  }

  if (run?.status === "partial_recovery") {
    findings.push({
      id: "partial-recovery",
      tone: "warning",
      title: "Partial recovery recorded",
      body: "The run recovered with a scoped rollback — confirm preserved services.",
      action: { label: "Inspect rollback scope →", href: `/projects/${projectId}/graphs` },
    });
  }

  if (conflicts > 0 && !negotiationResolved) {
    findings.push({
      id: "unresolved-conflicts",
      tone: "warning",
      title: "Unresolved constraint conflicts",
      body: `${conflicts} constraint conflict${conflicts === 1 ? "" : "s"} remain unresolved for this run.`,
      action: { label: "Open negotiation →", href: `/projects/${projectId}/orchestration` },
    });
  }

  if (pendingApprovals > 0 || run?.status === "awaiting_approval") {
    findings.push({
      id: "pending-approvals",
      tone: "info",
      title: "Plan awaiting approval",
      body:
        pendingApprovals > 0
          ? `${pendingApprovals} proposal${pendingApprovals === 1 ? "" : "s"} awaiting a decision.`
          : "This run is waiting on human approval before it can continue.",
      action: { label: "Review proposals →", href: `/projects/${projectId}/changes` },
    });
  }

  return findings;
}
