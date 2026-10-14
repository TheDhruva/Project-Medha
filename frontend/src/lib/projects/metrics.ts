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

/* ------------------------------- scorecards -------------------------------- */

export interface ScorecardMetric {
  id: "code-quality" | "security" | "verification" | "readiness";
  title: string;
  /** 0-100, or null when the run has no evidence for this metric. */
  value: number | null;
  /** Short evidence line; also the "why" when value is null. */
  evidence: string;
  assessedAt: string | null;
  /** Short source revision the score was computed against, when known. */
  revision: string | null;
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

function scoreEvidence(score: ProductScore | undefined): string {
  if (!score) return "Score not computed for this run.";
  if (score.value == null) {
    const reason = score.evidence?.reason;
    return typeof reason === "string" ? `Not assessed: ${reason}.` : "Not assessed for this run.";
  }
  const ev = score.evidence ?? {};
  const parts: string[] = [];
  if (typeof ev.security_failures === "number") parts.push(`${ev.security_failures} security failures`);
  if (typeof ev.critic_security === "number") parts.push(`critic security ${ev.critic_security}`);
  if (typeof ev.blocking_failures === "number") parts.push(`${ev.blocking_failures} blocking failures`);
  if (ev.no_health_check) parts.push("no health check recorded");
  return parts.length > 0 ? parts.join(" · ") : "Evidence-backed score.";
}

export function deriveScorecards(input: {
  run: RunSummary;
  verification: Record<string, unknown> | null;
  critic: Record<string, unknown> | null;
  scores: ScoresResponse | null;
  projectId: string;
}): ScorecardMetric[] {
  const { run, verification, critic, scores, projectId } = input;
  const isDemo = run.is_demo;
  const assessmentTime = scores?.scores?.deployment_readiness?.computed_at ?? run.updated_at;
  const revision =
    shortSha(scores?.scores?.deployment_readiness?.target_sha) ?? shortSha(run.target_revision);

  // Code quality — critic completeness (structure/config/compose checks).
  const criticBreakdown = asRecord(critic?.breakdown);
  const codeValue = asNumber(criticBreakdown?.completeness);
  const criticFindings = Array.isArray(critic?.findings) ? critic.findings.length : 0;
  const criticRec = typeof critic?.recommendation === "string" ? critic.recommendation : null;

  // Verification confidence — verifier score + observed check counts.
  const checks = Array.isArray(verification?.checks) ? verification.checks : [];
  const verificationSummary: VerificationSummary | null = verification
    ? {
        passed: typeof verification.passed === "boolean" ? verification.passed : null,
        score: asNumber(verification.score),
        total: checks.length,
        failed: checks.filter(
          (c) => asRecord(c)?.status === "fail",
        ).length,
        summary: typeof verification.summary === "string" ? verification.summary : null,
        blocking: [],
      }
    : null;
  const verificationValue =
    verificationSummary && verificationSummary.total > 0 ? verificationSummary.score : null;
  const passedCount = checks.filter((c) => asRecord(c)?.status === "pass").length;
  const warningCount = checks.filter((c) => asRecord(c)?.status === "warning").length;

  const securityScore = scores?.scores?.security;
  const readinessScore = scores?.scores?.deployment_readiness;

  return [
    {
      id: "code-quality",
      title: "Code Quality",
      value: codeValue,
      evidence:
        codeValue != null
          ? `${criticRec ?? "Critic"} · ${criticFindings} finding${criticFindings === 1 ? "" : "s"}`
          : "Critic has not assessed this run.",
      assessedAt: critic ? assessmentTime : null,
      revision,
      isDemo,
      href: `/projects/${projectId}/verification`,
    },
    {
      id: "security",
      title: "Security Posture",
      value: securityScore?.value ?? null,
      evidence: scoreEvidence(securityScore),
      assessedAt: securityScore?.computed_at ?? null,
      revision: shortSha(securityScore?.target_sha) ?? revision,
      isDemo,
      href: `/projects/${projectId}/verification`,
    },
    {
      id: "verification",
      title: "Verification Confidence",
      value: verificationValue,
      evidence:
        verificationSummary && verificationSummary.total > 0
          ? `${passedCount}/${verificationSummary.total} checks passed` +
            (verificationSummary.failed > 0
              ? ` · ${verificationSummary.failed} failed`
              : "") +
            (warningCount > 0 ? ` · ${warningCount} warning${warningCount === 1 ? "" : "s"}` : "")
          : "No verification artifact for this run.",
      assessedAt: verification ? assessmentTime : null,
      revision,
      isDemo,
      href: `/projects/${projectId}/verification`,
    },
    {
      id: "readiness",
      title: "Deployment Readiness",
      value: readinessScore?.value ?? null,
      evidence: scoreEvidence(readinessScore),
      assessedAt: readinessScore?.computed_at ?? null,
      revision: shortSha(readinessScore?.target_sha) ?? revision,
      isDemo,
      href: `/projects/${projectId}/graphs`,
    },
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
