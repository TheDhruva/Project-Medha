"use client";

import { useMemo } from "react";
import { CheckCircle2, Clock, ShieldAlert, Sparkles, XCircle } from "lucide-react";
import type { RunHealth, RunSummary } from "@/lib/api/client";
import type { VerificationSummary } from "@/lib/projects/useProjectData";
import { formatActivity } from "@/lib/projects/projects";
import { cn } from "@/lib/ui/cn";

interface FindingLike {
  id: string;
  tone: "error" | "warning" | "info" | "neutral";
  title: string;
}

interface EngineeringMetricsProps {
  runs: RunSummary[];
  findings: FindingLike[];
  verification: VerificationSummary | null;
  health: RunHealth | null;
  loading?: boolean;
}

export function EngineeringMetrics({
  runs,
  findings,
  verification,
  health,
  loading = false,
}: EngineeringMetricsProps) {
  // 1. Commits Assessed: unique commits for which MEDHA recorded a completed assessment
  const assessedCount = useMemo(() => {
    const shas = new Set<string>();
    for (const r of runs) {
      if (
        r.target_revision &&
        (r.status === "completed" ||
          r.analysis_status === "completed" ||
          r.result_kind === "success")
      ) {
        shas.add(r.target_revision.toLowerCase());
      }
    }
    return shas.size;
  }, [runs]);

  // 2. Open Findings: currently unresolved findings with severity breakdown
  const { blockers, warnings, totalOpen } = useMemo(() => {
    const errorCount = findings.filter((f) => f.tone === "error").length;
    const warnCount = findings.filter((f) => f.tone === "warning").length;
    return {
      blockers: errorCount,
      warnings: warnCount,
      totalOpen: errorCount + warnCount,
    };
  }, [findings]);

  // 3. Latest Verification: result and timestamp of latest completed verification
  const verificationMetric = useMemo(() => {
    const latestCompleted = runs.find(
      (r) => r.status === "completed" || r.status === "failed",
    );
    if (!verification && !latestCompleted) {
      return {
        label: "Not verified",
        sub: "No verification recorded",
        tone: "neutral" as const,
        icon: Clock,
      };
    }
    if (verification?.passed === true) {
      return {
        label: "Passed",
        sub: latestCompleted ? `Verified ${formatActivity(latestCompleted.updated_at)}` : "Verified",
        tone: "success" as const,
        icon: CheckCircle2,
      };
    }
    if (verification?.passed === false) {
      return {
        label: "Failed",
        sub: latestCompleted ? `Checked ${formatActivity(latestCompleted.updated_at)}` : "Verification gate",
        tone: "error" as const,
        icon: XCircle,
      };
    }
    if (latestCompleted?.status === "completed") {
      return {
        label: "Passed",
        sub: `Verified ${formatActivity(latestCompleted.updated_at)}`,
        tone: "success" as const,
        icon: CheckCircle2,
      };
    }
    return {
      label: "Incomplete",
      sub: "Partial verification",
      tone: "warning" as const,
      icon: Clock,
    };
  }, [verification, runs]);

  // 4. Deployment Health: current deployment state & timestamp of last successful deploy
  const deploymentMetric = useMemo(() => {
    const lastSuccess = runs.find(
      (r) => r.status === "completed" && r.result_kind === "success",
    );
    const lastSuccessText = lastSuccess ? formatActivity(lastSuccess.updated_at) : null;
    const rawHealth = (health?.health_status ?? "").toLowerCase();

    if (rawHealth === "healthy") {
      return {
        label: "Healthy",
        sub: lastSuccessText ? `Deployed ${lastSuccessText}` : "Probes passing",
        tone: "success" as const,
      };
    }
    if (rawHealth === "unhealthy" || rawHealth === "failed") {
      return {
        label: "Unhealthy",
        sub: lastSuccessText ? `Last good ${lastSuccessText}` : "Probes failing",
        tone: "error" as const,
      };
    }
    if (rawHealth === "degraded" || rawHealth === "running") {
      return {
        label: "Checking",
        sub: "Health check pending",
        tone: "warning" as const,
      };
    }
    if (lastSuccess) {
      return {
        label: "Recorded",
        sub: `Deployed ${lastSuccessText}`,
        tone: "neutral" as const,
      };
    }
    return {
      label: "Not deployed",
      sub: "No deployments recorded",
      tone: "neutral" as const,
    };
  }, [health, runs]);

  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="engineering-metrics">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-16 animate-pulse rounded-lg border border-medha-border bg-medha-surface" />
        ))}
      </div>
    );
  }

  return (
    <div
      className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-medha-border bg-medha-border shadow-sm sm:grid-cols-4"
      data-testid="engineering-metrics"
    >
      {/* 1. Commits Assessed */}
      <div className="flex flex-col justify-between bg-medha-surface p-3 sm:p-3.5">
        <span className="text-[11px] font-semibold tracking-wider text-medha-secondary uppercase">
          Commits Assessed
        </span>
        <div className="mt-1 flex items-baseline gap-1.5">
          <span className="text-[18px] sm:text-[20px] font-semibold text-medha-text">
            {assessedCount}
          </span>
          <span className="text-[12px] text-medha-secondary">
            {assessedCount === 1 ? "commit" : "commits"}
          </span>
        </div>
        <span className="mt-1 truncate text-[11.5px] text-medha-secondary">
          {runs.length === 0 ? "No recorded runs" : `Across ${runs.length} run${runs.length === 1 ? "" : "s"}`}
        </span>
      </div>

      {/* 2. Open Findings */}
      <div className="flex flex-col justify-between bg-medha-surface p-3 sm:p-3.5">
        <span className="text-[11px] font-semibold tracking-wider text-medha-secondary uppercase">
          Open Findings
        </span>
        <div className="mt-1 flex items-baseline gap-1.5">
          <span
            className={cn(
              "text-[18px] sm:text-[20px] font-semibold",
              blockers > 0
                ? "text-medha-danger"
                : warnings > 0
                  ? "text-medha-warning"
                  : "text-medha-text",
            )}
          >
            {totalOpen}
          </span>
          <span className="text-[12px] text-medha-secondary">unresolved</span>
        </div>
        <span className="mt-1 truncate text-[11.5px] text-medha-secondary">
          {totalOpen === 0
            ? "Clean assessment"
            : blockers > 0 && warnings > 0
              ? `${blockers} critical · ${warnings} warning`
              : blockers > 0
                ? `${blockers} critical blocker`
                : `${warnings} warning`}
        </span>
      </div>

      {/* 3. Latest Verification */}
      <div className="flex flex-col justify-between bg-medha-surface p-3 sm:p-3.5">
        <span className="text-[11px] font-semibold tracking-wider text-medha-secondary uppercase">
          Latest Verification
        </span>
        <div className="mt-1 flex items-center gap-1.5">
          <span
            className={cn(
              "text-[16px] sm:text-[18px] font-semibold",
              verificationMetric.tone === "success" && "text-medha-success",
              verificationMetric.tone === "error" && "text-medha-danger",
              verificationMetric.tone === "warning" && "text-medha-warning",
              verificationMetric.tone === "neutral" && "text-medha-secondary",
            )}
          >
            {verificationMetric.label}
          </span>
        </div>
        <span className="mt-1 truncate text-[11.5px] text-medha-secondary">
          {verificationMetric.sub}
        </span>
      </div>

      {/* 4. Deployment Health */}
      <div className="flex flex-col justify-between bg-medha-surface p-3 sm:p-3.5">
        <span className="text-[11px] font-semibold tracking-wider text-medha-secondary uppercase">
          Deployment Health
        </span>
        <div className="mt-1 flex items-center gap-1.5">
          <span
            className={cn(
              "text-[16px] sm:text-[18px] font-semibold",
              deploymentMetric.tone === "success" && "text-medha-success",
              deploymentMetric.tone === "error" && "text-medha-danger",
              deploymentMetric.tone === "warning" && "text-medha-warning",
              deploymentMetric.tone === "neutral" && "text-medha-secondary",
            )}
          >
            {deploymentMetric.label}
          </span>
        </div>
        <span className="mt-1 truncate text-[11.5px] text-medha-secondary">
          {deploymentMetric.sub}
        </span>
      </div>
    </div>
  );
}

