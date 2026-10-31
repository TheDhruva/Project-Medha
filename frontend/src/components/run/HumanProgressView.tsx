"use client";

import React, { useMemo } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock,
  Info,
  Loader2,
  MinusCircle,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Terminal,
  XCircle,
} from "lucide-react";
import type { DeploymentSnapshot, VerificationCheck } from "@/lib/demo/types";
import {
  DEPLOYMENT_BLOCKED_CODES,
  DEPLOYMENT_NOT_APPLICABLE_CODES,
} from "@/lib/projects/projects";
import { cn } from "@/lib/ui/cn";

export interface HumanProgressViewProps {
  snapshot: DeploymentSnapshot;
  projectId?: string;
  onRetry?: () => void;
  retrying?: boolean;
  onToggleTechnical?: () => void;
  isTechnicalOpen?: boolean;
}

export type PhaseStatus =
  | "completed"
  | "in_progress"
  | "pending"
  | "not_needed"
  | "blocked"
  | "failed";

export interface ProgressPhase {
  id: string;
  title: string;
  description: string;
  status: PhaseStatus;
  statusNote?: string;
  details?: string[];
}

export function parsePlainLanguageError(message: string): {
  whatHappened: string;
  whyItMatters: string | null;
  whatYouCanDo: string | null;
} {
  if (!message) {
    return {
      whatHappened: "An unexpected error occurred during execution.",
      whyItMatters: null,
      whatYouCanDo: "Retry the run or inspect the technical log for details.",
    };
  }

  // Parse What happened / Why it matters / What you can do without requiring es2018 regex flag
  const whatMatch = /What happened:\s*([\s\S]*?)(?=\s*Why it matters:|\s*What you can do:|$)/i.exec(message);
  const whyMatch = /Why it matters:\s*([\s\S]*?)(?=\s*What you can do:|$)/i.exec(message);
  const canDoMatch = /What you can do:\s*([\s\S]*?)$/i.exec(message);

  if (whatMatch && whatMatch[1].trim()) {
    return {
      whatHappened: whatMatch[1].trim(),
      whyItMatters: whyMatch ? whyMatch[1].trim() : null,
      whatYouCanDo: canDoMatch ? canDoMatch[1].trim() : null,
    };
  }

  // Heuristic conversion of common errors into plain language
  const lower = message.toLowerCase();
  if (lower.includes("docker daemon is not running") || lower.includes("docker is not running")) {
    return {
      whatHappened: "MEDHA could not start the deployment environment because Docker is not running.",
      whyItMatters:
        "MEDHA could not launch the application to test its running behavior. Repository checks and security analysis that do not require Docker remain valid.",
      whatYouCanDo: "Start Docker Desktop and retry deployment.",
    };
  }

  if (lower.includes("git") && (lower.includes("not found") || lower.includes("clone") || lower.includes("unreachable"))) {
    return {
      whatHappened: "MEDHA could not access or clone the specified repository revision.",
      whyItMatters: "Code analysis and verification could not start without repository source files.",
      whatYouCanDo: "Check that the repository exists, is publicly accessible or has GitHub App permissions, and try again.",
    };
  }

  if (lower.includes("timeout") || lower.includes("timed out")) {
    return {
      whatHappened: "A check or build step exceeded the allowed execution time limit.",
      whyItMatters: "The run stopped to prevent infinite loops and resource exhaustion.",
      whatYouCanDo: "Retry the analysis or verify that build and test scripts finish in a standard timeframe.",
    };
  }

  return {
    whatHappened: message.trim(),
    whyItMatters: "This issue prevented completing the full automated assessment.",
    whatYouCanDo: "Review repository configuration, ensure dependencies install cleanly, and retry.",
  };
}

export function deriveProgressPhases(snapshot: DeploymentSnapshot): ProgressPhase[] {
  const isFailed = snapshot.runStatus === "failed" || snapshot.runStatus === "partial_recovery";
  const isCompleted = snapshot.runStatus === "succeeded";
  const isRunning = snapshot.runStatus === "running";

  const code = (snapshot.result?.code ?? "").toUpperCase();
  const isDeploymentBlocked = isFailed && DEPLOYMENT_BLOCKED_CODES.has(code);
  const isDeploymentNotApplicable = isDeploymentBlocked && DEPLOYMENT_NOT_APPLICABLE_CODES.has(code);

  const rawStages = snapshot.pipeline || [];
  const stageMap = new Map(rawStages.map((s) => [s.id.toLowerCase(), s.status.toLowerCase()]));

  const isStageDone = (st?: string) => st === "success" || st === "completed" || st === "warning";
  const isStageRunning = (st?: string) => st === "running";
  const isStageFailed = (st?: string) => st === "failed";

  // 1. Connecting to repository (Preflight / Checkout)
  const preflightStatus = stageMap.get("preflight");
  let p1Status: PhaseStatus = "completed";
  let p1Note = "Repository checked out and verified";

  if (isStageFailed(preflightStatus)) {
    p1Status = "failed";
    p1Note = "Could not access or clone repository";
  } else if (isStageRunning(preflightStatus) || (isRunning && !isStageDone(preflightStatus))) {
    p1Status = "in_progress";
    p1Note = "Verifying access and checking out selected revision…";
  }

  // 2. Understanding the code (Analyzer / Inventory)
  const analyzerStatus = stageMap.get("analyzer") || stageMap.get("analyze");
  let p2Status: PhaseStatus = "completed";
  let p2Note = "Application stack, entry points, and dependencies identified";

  if (p1Status === "in_progress") {
    p2Status = "pending";
    p2Note = "Waiting for repository checkout";
  } else if (isStageFailed(analyzerStatus)) {
    p2Status = "failed";
    p2Note = "Code structure analysis failed";
  } else if (isStageRunning(analyzerStatus) || (isRunning && !isStageDone(analyzerStatus))) {
    p2Status = "in_progress";
    p2Note = "Analyzing code structure, manifests, and framework…";
  }

  // 3. Checking code and security (Security agent / Quality checks)
  const securityStatus = stageMap.get("security") || stageMap.get("plan");
  let p3Status: PhaseStatus = "completed";
  let p3Note = "Security scanners, secret detection, and code quality analyzed";

  if (p2Status === "pending" || p2Status === "in_progress") {
    p3Status = "pending";
    p3Note = "Waiting for code structure analysis";
  } else if (isStageFailed(securityStatus)) {
    p3Status = "failed";
    p3Note = "Security analysis failed";
  } else if (isStageRunning(securityStatus) || (isRunning && !isStageDone(securityStatus))) {
    p3Status = "in_progress";
    p3Note = "Running security scanners and code checks…";
  }

  // 4. Verifying the project (Verifier agent / Tests / Build checks)
  const verifierStatus = stageMap.get("verifier") || stageMap.get("verify");
  let p4Status: PhaseStatus = "completed";
  let p4Note = "Project requirements and test constraints validated";

  if (p3Status === "pending" || p3Status === "in_progress") {
    p4Status = "pending";
    p4Note = "Waiting for security checks";
  } else if (isStageFailed(verifierStatus)) {
    p4Status = "failed";
    p4Note = "Verification assertions failed";
  } else if (isStageRunning(verifierStatus) || (isRunning && !isStageDone(verifierStatus))) {
    p4Status = "in_progress";
    p4Note = "Evaluating tests, constraints, and configuration…";
  }

  // 5. Preparing deployment assessment (Docker / Execution)
  const executeStatus = stageMap.get("execute") || stageMap.get("executor");
  let p5Status: PhaseStatus = "completed";
  let p5Note = "Deployment environment and readiness confirmed";

  if (isDeploymentNotApplicable) {
    p5Status = "not_needed";
    p5Note = "Not needed for this project (no standalone deployable web app)";
  } else if (isDeploymentBlocked) {
    p5Status = "blocked";
    p5Note = code.includes("DOCKER")
      ? "Deployment blocked: Docker daemon is not running"
      : "Deployment blocked: Target environment prerequisites not met";
  } else if (p4Status === "pending" || p4Status === "in_progress") {
    p5Status = "pending";
    p5Note = "Waiting for project verification";
  } else if (isStageFailed(executeStatus)) {
    p5Status = "failed";
    p5Note = "Deployment execution failed";
  } else if (isStageRunning(executeStatus) || (isRunning && !isStageDone(executeStatus))) {
    p5Status = "in_progress";
    p5Note = "Assessing deployment environment and container health…";
  }

  // 6. Preparing results (Report / Scores / Summary)
  let p6Status: PhaseStatus = "completed";
  let p6Note = "All four engineering scorecards and findings recorded";

  if (isRunning) {
    p6Status = "pending";
    p6Note = "Will compute scores upon phase completion";
  } else if (isFailed && p1Status === "failed") {
    p6Status = "not_needed";
    p6Note = "Results unavailable due to early checkout failure";
  }

  return [
    {
      id: "connect",
      title: "Connecting to repository",
      description: "Retrieving the selected revision and confirming repository access",
      status: p1Status,
      statusNote: p1Note,
    },
    {
      id: "analyze",
      title: "Understanding the code",
      description: "Identifying languages, frameworks, project structure, and entry points",
      status: p2Status,
      statusNote: p2Note,
    },
    {
      id: "security",
      title: "Checking code and security",
      description: "Running quality checks, vulnerability scanners, and dependency analysis",
      status: p3Status,
      statusNote: p3Note,
    },
    {
      id: "verify",
      title: "Verifying the project",
      description: "Evaluating test suites, builds, and architectural constraints",
      status: p4Status,
      statusNote: p4Note,
    },
    {
      id: "deploy",
      title: "Preparing deployment assessment",
      description: "Evaluating runtime feasibility, port contracts, and container health",
      status: p5Status,
      statusNote: p5Note,
    },
    {
      id: "results",
      title: "Preparing results",
      description: "Saving findings, computing engineering scores, and preparing the report",
      status: p6Status,
      statusNote: p6Note,
    },
  ];
}

export function HumanProgressView({
  snapshot,
  projectId,
  onRetry,
  retrying,
  onToggleTechnical,
  isTechnicalOpen,
}: HumanProgressViewProps) {
  const phases = useMemo(() => deriveProgressPhases(snapshot), [snapshot]);

  const isFailed = snapshot.runStatus === "failed" || snapshot.runStatus === "partial_recovery";
  const isCompleted = snapshot.runStatus === "succeeded";
  const code = (snapshot.result?.code ?? "").toUpperCase();
  const isDeploymentBlocked = isFailed && DEPLOYMENT_BLOCKED_CODES.has(code);
  const isDeploymentNotApplicable = isDeploymentBlocked && DEPLOYMENT_NOT_APPLICABLE_CODES.has(code);

  const rawErrorMessage = snapshot.result?.message ?? snapshot.explain.technicalText ?? "";
  const plainError = useMemo(
    () => (isFailed ? parsePlainLanguageError(rawErrorMessage) : null),
    [isFailed, rawErrorMessage],
  );

  // Extract checks needing attention if present
  const importantFindings = useMemo(() => {
    const raw = snapshot.verification?.checks;
    if (!Array.isArray(raw)) return [];
    return raw.filter((c: VerificationCheck) => c.status === "fail" || c.status === "warning");
  }, [snapshot.verification]);

  return (
    <div className="space-y-4" data-testid="human-progress-view">
      {/* 1. Overall Progress Header Card */}
      <div className="rounded-xl border border-medha-border bg-white p-4 sm:p-5 shadow-xs">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-medha-border pb-3.5">
          <div>
            <h2 className="text-[16px] font-semibold text-medha-text">Analysis Progress</h2>
            <p className="text-[12.5px] text-medha-secondary">
              {snapshot.runStatus === "running"
                ? "MEDHA is actively analyzing your repository"
                : isDeploymentNotApplicable
                  ? "Repository analysis complete · Deployment not applicable"
                  : isDeploymentBlocked
                    ? "Repository analysis complete · Deployment blocked"
                    : isFailed
                      ? "Analysis encountered an issue"
                      : "Repository assessment complete"}
            </p>
          </div>

          <div className="flex items-center gap-2">
            {onRetry ? (
              <button
                type="button"
                onClick={onRetry}
                disabled={retrying || snapshot.runStatus === "running"}
                className="inline-flex items-center gap-1.5 rounded-lg border border-medha-border bg-white px-3 py-1.5 text-[12.5px] font-medium text-medha-text transition hover:bg-medha-surface-muted disabled:opacity-50"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", retrying && "animate-spin")} />
                {retrying ? "Retrying…" : "Retry"}
              </button>
            ) : null}
          </div>
        </div>

        {/* Six Human-Readable Progress Phases */}
        <div className="mt-4 space-y-3">
          {phases.map((phase, idx) => {
            const isPhaseCompleted = phase.status === "completed";
            const isInProgress = phase.status === "in_progress";
            const isBlocked = phase.status === "blocked";
            const isNotNeeded = phase.status === "not_needed";
            const isFail = phase.status === "failed";
            const isPending = phase.status === "pending";

            return (
              <div
                key={phase.id}
                className={cn(
                  "flex items-start gap-3 rounded-lg border px-3.5 py-2.5 transition-all",
                  isInProgress && "border-medha-accent/40 bg-medha-accent-soft/20 ring-1 ring-medha-accent/20",
                  isPhaseCompleted && "border-medha-border bg-white",
                  isBlocked && "border-medha-warning/30 bg-medha-warning-soft/30",
                  isNotNeeded && "border-medha-border/60 bg-medha-surface-muted/40 opacity-75",
                  isFail && "border-medha-danger/30 bg-medha-danger-soft/20",
                  isPending && "border-medha-border/40 bg-medha-surface-soft/40 opacity-65",
                )}
              >
                {/* Phase Icon */}
                <div className="mt-0.5 shrink-0">
                  {isInProgress ? (
                    <Loader2 className="h-4 w-4 animate-spin text-medha-accent" aria-hidden />
                  ) : isPhaseCompleted ? (
                    <CheckCircle2 className="h-4 w-4 text-medha-success" aria-hidden />
                  ) : isBlocked ? (
                    <AlertTriangle className="h-4 w-4 text-medha-warning" aria-hidden />
                  ) : isNotNeeded ? (
                    <MinusCircle className="h-4 w-4 text-medha-secondary" aria-hidden />
                  ) : isFail ? (
                    <XCircle className="h-4 w-4 text-medha-danger" aria-hidden />
                  ) : (
                    <Circle className="h-4 w-4 text-medha-border-strong" aria-hidden />
                  )}
                </div>

                {/* Content */}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3
                      className={cn(
                        "text-[13.5px] font-semibold leading-snug",
                        isInProgress ? "text-medha-accent" : "text-medha-text",
                      )}
                    >
                      {idx + 1}. {phase.title}
                    </h3>
                    {phase.statusNote ? (
                      <span
                        className={cn(
                          "text-[11.5px] font-medium",
                          isInProgress && "text-medha-accent",
                          isPhaseCompleted && "text-medha-success",
                          isBlocked && "text-medha-warning",
                          isNotNeeded && "text-medha-secondary",
                          isFail && "text-medha-danger",
                          isPending && "text-medha-tertiary",
                        )}
                      >
                        {phase.statusNote}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-0.5 text-[12px] text-medha-secondary leading-relaxed">
                    {phase.description}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 2. Structured Plain-Language Error / Blocker (if applicable) */}
      {isFailed && plainError ? (
        <div
          role="alert"
          className="rounded-xl border border-medha-danger/30 bg-medha-danger-soft p-4 sm:p-5 space-y-3"
          data-testid="plain-language-error"
        >
          <div className="flex items-center gap-2 text-medha-danger font-semibold text-[14px]">
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
            <span>Action Required</span>
          </div>

          <div className="space-y-2 text-[13px] text-medha-text">
            <div>
              <p className="font-semibold text-medha-danger">What happened:</p>
              <p className="mt-0.5 leading-relaxed text-medha-text">{plainError.whatHappened}</p>
            </div>

            {plainError.whyItMatters ? (
              <div>
                <p className="font-semibold text-medha-text">Why it matters:</p>
                <p className="mt-0.5 leading-relaxed text-medha-secondary">{plainError.whyItMatters}</p>
              </div>
            ) : null}

            {plainError.whatYouCanDo ? (
              <div className="rounded-lg border border-medha-danger/20 bg-white/70 p-3">
                <p className="font-semibold text-medha-text">What you can do:</p>
                <p className="mt-0.5 leading-relaxed text-medha-text">{plainError.whatYouCanDo}</p>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {/* 3. Important Findings (if any) */}
      {importantFindings.length > 0 ? (
        <div className="rounded-xl border border-medha-border bg-white p-4 sm:p-5">
          <div className="flex items-center justify-between gap-2 border-b border-medha-border pb-2.5">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-medha-warning" />
              <h3 className="text-[14px] font-semibold text-medha-text">Important Findings</h3>
            </div>
            <span className="text-[12px] text-medha-secondary">
              {importantFindings.length} issue{importantFindings.length === 1 ? "" : "s"} requiring review
            </span>
          </div>

          <ul className="mt-3 divide-y divide-medha-border/60">
            {importantFindings.slice(0, 5).map((finding, fIdx) => (
              <li key={fIdx} className="py-2 flex items-start gap-2.5 text-[12.5px]">
                <span className="mt-0.5 h-2 w-2 rounded-full bg-medha-warning shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-medha-text truncate">
                    {finding.name || finding.id || "Finding"}
                  </p>
                  {finding.message ? (
                    <p className="text-[11.5px] text-medha-secondary line-clamp-2">
                      {finding.message}
                    </p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : isCompleted ? (
        <div className="flex items-center gap-2.5 rounded-xl border border-medha-success/30 bg-medha-success-soft/30 p-4 text-[13px] text-medha-success">
          <ShieldCheck className="h-4 w-4 shrink-0" />
          <span>All high-priority quality and security checks passed cleanly.</span>
        </div>
      ) : null}

      {/* 4. Secondary Option: Technical Debugging Details */}
      {onToggleTechnical ? (
        <div className="pt-2 text-center">
          <button
            type="button"
            onClick={onToggleTechnical}
            className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-medha-secondary hover:text-medha-accent transition-colors"
          >
            <Terminal className="h-3.5 w-3.5" />
            <span>
              {isTechnicalOpen
                ? "Hide technical execution details"
                : "Inspect technical details (graph, agents, logs)"}
            </span>
            {isTechnicalOpen ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      ) : null}
    </div>
  );
}
