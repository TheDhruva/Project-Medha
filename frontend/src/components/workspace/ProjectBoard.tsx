"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, PlayCircle } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { EmptyState, ErrorBox, Skeleton } from "@/components/ui/primitives";
import { DeploymentDetailsPopover } from "@/components/workspace/DeploymentDetailsPopover";
import { MetricCard } from "@/components/workspace/MetricCard";
import { EngineeringMetrics } from "@/components/workspace/EngineeringMetrics";
import { GitCommitGraph } from "@/components/workspace/GitCommitGraph";
import { deriveFindings, deriveScorecards } from "@/lib/projects/metrics";
import { summarizeVerification, useProjectData } from "@/lib/projects/useProjectData";
import { canonicalRepoKey, isRunningStatus, runOutcome, type OutcomeTone } from "@/lib/projects/projects";
import {
  createProjectRun,
  fetchConfigStatus,
  fetchScores,
  type ExecutionReadiness,
  type ScoresResponse,
} from "@/lib/api/client";
import { cn } from "@/lib/ui/cn";

const STATUS_DOT_CLASSES: Record<OutcomeTone, string> = {
  success: "bg-medha-success",
  warning: "bg-medha-warning",
  error: "bg-medha-danger",
  info: "bg-medha-info",
  neutral: "bg-medha-secondary",
};

export function ProjectBoard({ projectId }: { projectId: string }) {
  const router = useRouter();
  const {
    project,
    repo,
    name,
    runs,
    loading,
    error,
    backendReachable,
    latest,
    selectedId,
    selectRun,
    hydration,
    hydrating,
    proposals,
    refresh,
  } = useProjectData(projectId);

  const [scores, setScores] = useState<ScoresResponse | null>(null);
  const [readiness, setReadiness] = useState<ExecutionReadiness | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const selected = useMemo(
    () => runs.find((r) => r.deployment_id === selectedId) ?? latest,
    [runs, selectedId, latest],
  );

  const selectedIndex = useMemo(
    () => (selected ? runs.findIndex((r) => r.deployment_id === selected.deployment_id) : -1),
    [runs, selected],
  );

  const verification = useMemo(
    () => summarizeVerification(hydration?.verification ?? null),
    [hydration],
  );

  const scorecards = useMemo(
    () =>
      selected
        ? deriveScorecards({
            run: selected,
            verification: hydration?.verification ?? null,
            critic: hydration?.critic ?? null,
            scores,
            projectId,
          })
        : [],
    [selected, hydration, scores, projectId],
  );

  const securityFailures = useMemo(() => {
    const value = scores?.scores?.security?.evidence?.security_failures;
    return typeof value === "number" ? value : null;
  }, [scores]);

  const conflicts = useMemo(
    () => (hydration?.constraints ?? []).filter((c) => c.status === "conflict"),
    [hydration],
  );

  const pendingApprovals = useMemo(
    () => proposals.filter((p) => p.status === "ready" || p.status === "pending"),
    [proposals],
  );

  const findings = useMemo(
    () =>
      deriveFindings({
        run: selected,
        readiness,
        verification,
        securityFailures,
        conflicts: conflicts.length,
        negotiationResolved: hydration?.negotiation?.status === "resolved",
        pendingApprovals: pendingApprovals.length,
        projectId,
      }),
    [selected, readiness, verification, securityFailures, conflicts, hydration, pendingApprovals, projectId],
  );

  const blockers = findings.filter((f) => f.tone === "error").length;

  const repoIdentity = useMemo(() => {
    if (project) {
      return {
        label: `${project.repo_owner}/${project.repo_name}`,
        href: `https://github.com/${project.repo_owner}/${project.repo_name}`,
      };
    }
    const key = repo ? canonicalRepoKey(repo) : null;
    return key
      ? { label: key, href: `https://github.com/${key}` }
      : { label: repo ?? "", href: null };
  }, [project, repo]);

  // Score snapshots for the selected run
  useEffect(() => {
    setScores(null);
    if (!selectedId) return;
    let cancelled = false;
    fetchScores(selectedId)
      .then((value) => {
        if (!cancelled) setScores(value);
      })
      .catch(() => {
        if (!cancelled) setScores(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  // Execution readiness
  useEffect(() => {
    let cancelled = false;
    fetchConfigStatus()
      .then((status) => {
        if (!cancelled) setReadiness(status?.execution_readiness ?? null);
      })
      .catch(() => {
        if (!cancelled) setReadiness(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const startRun = useCallback(async () => {
    if (!project) return;
    setStarting(true);
    setStartError(null);
    try {
      const response = await createProjectRun(project.project_id);
      router.push(`/projects/${projectId}/runs/${response.deployment_id}`);
    } catch (err) {
      setStartError(err instanceof Error ? err.message : "Cannot start the analysis run.");
    } finally {
      setStarting(false);
    }
  }, [project, projectId, router]);

  // Status indicators: Deployment and Analysis are completely separated
  const latestOutcome = latest ? runOutcome(latest) : null;

  const analysisInfo = useMemo(() => {
    if (!latest) {
      return { label: "Not analyzed", tone: "neutral" as OutcomeTone };
    }
    return latestOutcome?.analysis ?? { label: "Not analyzed", tone: "neutral" as OutcomeTone };
  }, [latest, latestOutcome]);

  const deploymentInfo = useMemo(() => {
    if (!latest) {
      return { label: "Not deployed", tone: "neutral" as OutcomeTone };
    }
    if (latestOutcome?.deployment) {
      return latestOutcome.deployment;
    }
    if (isRunningStatus(latest.status)) {
      if (latest.current_stage === "EXECUTE" || latest.current_stage === "DEPLOY") {
        return { label: "Deploying", tone: "info" as OutcomeTone };
      }
      return { label: "Deployment pending", tone: "neutral" as OutcomeTone };
    }
    return { label: "Not deployed", tone: "neutral" as OutcomeTone };
  }, [latest, latestOutcome]);

  if (!repo) {
    return (
      <AppShell>
        <EmptyState
          title="Project not found"
          body="This project link does not decode to a known repository. Projects are keyed by repository URL."
          action={
            <Link
              href="/projects"
              className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-medha-accent-hover"
            >
              Back to projects
            </Link>
          }
        />
      </AppShell>
    );
  }

  // Active run state detection
  const runHref = selected ? `/projects/${projectId}/runs/${selected.deployment_id}` : null;
  const activeRunHref = latest && isRunningStatus(latest.status)
    ? `/projects/${projectId}/runs/${latest.deployment_id}`
    : null;
  const runBlocked = starting || activeRunHref != null;

  const secondaryActions = (
    <>
      {activeRunHref ? (
        <Link
          href={activeRunHref}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-medha-run/25 bg-medha-run-soft px-3 text-[13px] font-semibold text-medha-run-ink transition hover:brightness-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
        >
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          View active run
        </Link>
      ) : null}
      {(pendingApprovals.length > 0 || selected?.status === "awaiting_approval") && !activeRunHref ? (
        <Link
          href={`/projects/${projectId}/changes`}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-medha-border bg-medha-surface px-3 text-[13px] font-medium text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
        >
          Review plan ({pendingApprovals.length || 1})
        </Link>
      ) : null}
      {selected?.status === "failed" && runHref ? (
        <Link
          href={runHref}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-medha-border bg-medha-surface px-3 text-[13px] font-medium text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
        >
          Inspect failure
        </Link>
      ) : null}
    </>
  );

  const primaryAction = project ? (
    <button
      type="button"
      onClick={() => void startRun()}
      disabled={runBlocked}
      title={
        activeRunHref
          ? "An analysis run is already active — view it instead of starting a duplicate."
          : "Start a new analysis run for this repository and branch"
      }
      aria-disabled={runBlocked}
      className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-medha-accent px-3.5 text-[13px] font-semibold text-white transition hover:bg-medha-accent-hover disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
    >
      {starting ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
      ) : (
        <PlayCircle className="h-3.5 w-3.5" aria-hidden />
      )}
      {starting ? "Starting…" : "Run analysis"}
    </button>
  ) : (
    <Link
      href="/verify"
      className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-medha-accent px-3.5 text-[13px] font-semibold text-white transition hover:bg-medha-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
    >
      <PlayCircle className="h-3.5 w-3.5" aria-hidden /> Run analysis
    </Link>
  );

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-[1280px] space-y-6">
        {/* ============================================================ */}
        {/* 1. Project Header                                            */}
        {/* ============================================================ */}
        <div className="flex flex-col gap-4 border-b border-medha-border pb-5 sm:flex-row sm:items-start sm:justify-between">
          {/* Left: Project identity */}
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-[24px] font-semibold leading-tight text-medha-text">
              {name || repoIdentity.label || "Project"}
            </h1>
            <div className="mt-1 flex items-center gap-1.5 text-[13px] text-medha-secondary">
              {repoIdentity.href ? (
                <a
                  href={repoIdentity.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-mono transition-colors hover:text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
                >
                  {repoIdentity.label}
                </a>
              ) : (
                <span className="font-mono">{repoIdentity.label}</span>
              )}
              {project?.branch ? (
                <>
                  <span className="text-medha-secondary/60" aria-hidden>·</span>
                  <span className="font-mono">{project.branch}</span>
                </>
              ) : null}
            </div>
          </div>

          {/* Right: Statuses & Actions */}
          <div className="flex shrink-0 flex-col gap-3 sm:items-end">
            {/* Status indicators */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 sm:justify-end">
              {/* Deployment status */}
              <div className="flex items-center gap-1.5" data-testid="deployment-status">
                <span
                  className={cn("h-2 w-2 rounded-full shrink-0", STATUS_DOT_CLASSES[deploymentInfo.tone])}
                  aria-hidden
                />
                <span className="text-[12px] font-medium tracking-wide uppercase text-medha-secondary">
                  {deploymentInfo.label}
                </span>
              </div>

              {/* Analysis status */}
              <div className="flex items-center gap-1.5" data-testid="analysis-status">
                <span
                  className={cn("h-2 w-2 rounded-full shrink-0", STATUS_DOT_CLASSES[analysisInfo.tone])}
                  aria-hidden
                />
                <span className="text-[12px] font-medium tracking-wide uppercase text-medha-secondary">
                  {analysisInfo.label}
                </span>
                {latest?.is_demo ? (
                  <span className="rounded border border-medha-border bg-medha-surface-muted px-1.5 py-0.5 text-[10.5px] font-semibold text-medha-secondary">
                    DEMO/MOCK
                  </span>
                ) : null}
              </div>
            </div>

            {/* Actions */}
            <div className="flex flex-wrap items-center gap-2" data-testid="project-actions">
              {secondaryActions}
              {primaryAction}
              <DeploymentDetailsPopover
                projectId={projectId}
                runs={runs}
                selectedRun={selected ?? null}
                selectedIndex={selectedIndex}
                health={hydration?.health ?? null}
                hydrating={hydrating}
                blockers={blockers}
                loading={loading && runs.length === 0}
                error={error}
                executionMode={hydration?.executionMode ?? null}
                starting={starting}
                canStartRun={Boolean(project)}
                onSelectRun={selectRun}
                onRetry={refresh}
                onStartRun={() => void startRun()}
              />
            </div>
          </div>
        </div>

        {/* Backend connectivity check / start error alerts */}
        {!backendReachable && !loading ? (
          <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} />
        ) : null}
        {startError ? (
          <p
            role="alert"
            className="rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3.5 py-2 text-[13.5px] leading-relaxed text-medha-text"
          >
            <span className="font-semibold text-medha-danger">Could not start the run. </span>
            {startError}
          </p>
        ) : null}

        {/* ============================================================ */}
        {/* 2. Four Engineering Scorecards                               */}
        {/* ============================================================ */}
        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" aria-label="Loading project">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-48 w-full rounded-lg" />
            ))}
          </div>
        ) : runs.length === 0 ? (
          <EmptyState
            title="No runs recorded for this repository"
            body="Start the first analysis to populate scorecards, findings, and execution evidence."
            action={
              project ? (
                <button
                  type="button"
                  onClick={() => void startRun()}
                  disabled={starting}
                  className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-medha-accent-hover disabled:opacity-60"
                >
                  {starting ? "Starting…" : "Start first analysis"}
                </button>
              ) : (
                <Link
                  href="/verify"
                  className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-medha-accent-hover"
                >
                  Start first analysis
                </Link>
              )
            }
          />
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" aria-label="Run scorecards">
            {scorecards.map((metric) => (
              <MetricCard key={metric.id} metric={metric} />
            ))}
          </div>
        )}

        {/* ============================================================ */}
        {/* 3. Compact Engineering Metrics                                */}
        {/* ============================================================ */}
        <EngineeringMetrics
          runs={runs}
          findings={findings}
          verification={verification}
          health={hydration?.health ?? null}
          loading={loading}
        />

        {/* ============================================================ */}
        {/* 4. Interactive Git Commit Graph                              */}
        {/* ============================================================ */}
        <GitCommitGraph
          projectId={projectId}
          defaultBranch={project?.branch}
          runs={runs}
        />
      </div>
    </AppShell>
  );
}
