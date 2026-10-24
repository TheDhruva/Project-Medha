"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, PlayCircle } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { MedhaFace, faceStateFromRun } from "@/components/medha/MedhaFace";
import { Badge, EmptyState, ErrorBox, Panel, Skeleton } from "@/components/ui/primitives";
import { DeploymentDetailsPopover } from "@/components/workspace/DeploymentDetailsPopover";
import { MetricCard } from "@/components/workspace/MetricCard";
import { OperationalStatus } from "@/components/workspace/OperationalStatus";
import { PipelineTimeline } from "@/components/workspace/PipelineTimeline";
import { RepositorySummaryBlock } from "@/components/workspace/RepositorySummaryBlock";
import {
  DeployHealthCard,
  EventsCard,
  FindingsStrip,
  LatestCommitCard,
  RepoIntelCard,
} from "@/components/workspace/DashboardSections";
import { deriveFindings, deriveScorecards } from "@/lib/projects/metrics";
import {
  derivePipeline,
  summarizeVerification,
  useProjectData,
} from "@/lib/projects/useProjectData";
import type { PhaseId } from "@/lib/projects/executionPhases";
import { canonicalRepoKey, formatActivity, isRunningStatus } from "@/lib/projects/projects";
import { selectRepositorySummary } from "@/lib/projects/repositorySummary";
import {
  createProjectRun,
  fetchConfigStatus,
  fetchScores,
  type ExecutionReadiness,
  type ScoresResponse,
} from "@/lib/api/client";

/* A finished run reports completion only — never health. Only genuinely
   positive evidence (verification passed, preserved services) uses green. */
function statusTone(status: string): "success" | "warning" | "error" | "info" | "neutral" {
  if (status === "partial_recovery" || status === "awaiting_approval") return "warning";
  if (status === "failed" || status === "cancelled") return "error";
  if (isRunningStatus(status)) return "info";
  return "neutral";
}

export function ProjectBoard({ projectId }: { projectId: string }) {
  const router = useRouter();
  const {
    project, repo, name, runs, loading, error, backendReachable,
    latest, selectedId, selectRun, hydration, hydrating, proposals, refresh,
  } = useProjectData(projectId);

  const [scores, setScores] = useState<ScoresResponse | null>(null);
  const [readiness, setReadiness] = useState<ExecutionReadiness | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [selectedPhase, setSelectedPhase] = useState<PhaseId | null>(null);

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

  // Phase details belong to one run; never carry them across a run or project switch.
  useEffect(() => {
    setSelectedPhase(null);
  }, [projectId, selected?.deployment_id]);

  const pipeline = useMemo(
    () =>
      hydration
        ? derivePipeline(
            hydration.logs,
            selected?.current_stage ?? null,
            selected?.status ?? null,
            selected?.error_code ?? null,
          )
        : [],
    [hydration, selected],
  );
  const conflicts = useMemo(
    () => (hydration?.constraints ?? []).filter((c) => c.status === "conflict"),
    [hydration],
  );
  const pendingApprovals = useMemo(
    () => proposals.filter((p) => p.status === "ready" || p.status === "pending"),
    [proposals],
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
  const repositorySummary = useMemo(() => selectRepositorySummary(runs), [runs]);
  const analyzing = latest ? isRunningStatus(latest.status) : false;
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
  const isCanonical = projectId.startsWith("prj_");

  // Score snapshots for the selected run (404/failure → honest "not assessed").
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

  // Execution readiness (operator configuration truth), loaded once.
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

  if (!repo) {
    return (
      <AppShell>
        <EmptyState
          title="Project not found"
          body="This project link does not decode to a known repository. Projects are keyed by repository URL."
          action={<Link href="/projects" className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white">Back to projects</Link>}
        />
      </AppShell>
    );
  }

  /* Header actions: Run analysis is always the prominent primary. While a
     run is genuinely active the button is disabled (no duplicate runs) and
     users are directed to the active run instead. Failed runs keep
     Inspect failure secondary and Run analysis enabled for retry. */
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
          className="inline-flex items-center gap-1.5 rounded-lg border border-medha-run/25 bg-medha-run-soft px-3 py-2 text-[14px] font-semibold text-medha-run-ink transition hover:brightness-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
        >
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          View active run
        </Link>
      ) : null}
      {(pendingApprovals.length > 0 || selected?.status === "awaiting_approval") && !activeRunHref ? (
        <Link
          href={`/projects/${projectId}/changes`}
          className="inline-flex items-center gap-1.5 rounded-lg border border-medha-border bg-medha-surface px-3 py-2 text-[14px] font-medium text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
        >
          Review plan ({pendingApprovals.length || 1})
        </Link>
      ) : null}
      {selected?.status === "failed" && runHref ? (
        <Link
          href={runHref}
          className="inline-flex items-center gap-1.5 rounded-lg border border-medha-border bg-medha-surface px-3 py-2 text-[14px] font-medium text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
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
      title={activeRunHref ? "An analysis run is already active — view it instead of starting a duplicate." : "Start a new analysis run for this repository and branch"}
      aria-disabled={runBlocked}
      className="inline-flex items-center gap-1.5 rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-medha-accent-hover disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
    >
      {starting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <PlayCircle className="h-4 w-4" aria-hidden />}
      {starting ? "Starting…" : "Run analysis"}
    </button>
  ) : (
    <Link
      href="/verify"
      className="inline-flex items-center gap-1.5 rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-medha-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
    >
      <PlayCircle className="h-4 w-4" aria-hidden /> Run analysis
    </Link>
  );

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-[1280px] space-y-3">
        {/* ---- Project header: identity, repository context, actions.
             Borderless so white panels below carry the content hierarchy. ---- */}
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="break-words text-[26px] font-semibold leading-tight tracking-tight text-medha-text">{name}</h1>
                {latest && !loading ? (
                  <span className="inline-flex items-center gap-1.5">
                    <MedhaFace
                      state={faceStateFromRun({
                        status: latest.status,
                        stage: latest.current_stage,
                        verificationPassed:
                          selected?.deployment_id === latest.deployment_id
                            ? verification?.passed ?? null
                            : null,
                      })}
                      size={24}
                    />
                    <Badge tone={statusTone(latest.status)}>{latest.status.replace(/_/g, " ")}</Badge>
                    {latest.is_demo ? <span className="text-[12px] font-semibold text-medha-tertiary">DEMO/MOCK</span> : null}
                  </span>
                ) : null}
              </div>
              <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-[12.5px] text-medha-tertiary">
                {repoIdentity.href ? (
                  <a
                    href={repoIdentity.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={repo ?? undefined}
                    className="medha-mono truncate font-medium text-medha-tertiary transition-colors hover:text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
                  >
                    {repoIdentity.label}
                  </a>
                ) : (
                  <span title={repo ?? undefined} className="medha-mono truncate">
                    {repoIdentity.label}
                  </span>
                )}
                {project?.branch ? (
                  <>
                    <span aria-hidden>·</span>
                    <span className="medha-mono">{project.branch}</span>
                  </>
                ) : null}
              </div>
              <RepositorySummaryBlock
                summary={repositorySummary.summary}
                revision={repositorySummary.revision}
                stale={repositorySummary.stale}
                loading={loading}
                analyzing={analyzing}
              />
            </div>
            <div
              className="flex shrink-0 flex-wrap items-start justify-end gap-2"
              data-testid="project-actions"
            >
              {secondaryActions}
              <div className="flex flex-col items-stretch gap-1.5">
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

        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}
        {startError ? (
          <p role="alert" className="rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3.5 py-2 text-[13.5px] leading-relaxed text-medha-text">
            <span className="font-semibold text-medha-danger">Could not start the run. </span>
            {startError}
          </p>
        ) : null}

        {loading ? (
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4" aria-label="Loading project">
            {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-40 w-full" />)}
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
                  className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                >
                  {starting ? "Starting…" : "Start first analysis"}
                </button>
              ) : (
                <Link href="/verify" className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white">Start first analysis</Link>
              )
            }
          />
        ) : (
          <>
            {/* Four semicircular assessment cards */}
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4" aria-label="Run scorecards">
              {scorecards.map((metric) => (
                <MetricCard key={metric.id} metric={metric} />
              ))}
            </div>

            {/* Pipeline + operational status */}
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
              <PipelineTimeline
                projectId={projectId}
                run={selected ?? null}
                stages={pipeline}
                logs={hydration?.logs ?? []}
                hydrating={hydrating}
                selectedPhase={selectedPhase}
                onSelectPhase={setSelectedPhase}
              />

              <OperationalStatus
                projectId={projectId}
                run={selected ?? null}
                stages={pipeline}
                logs={hydration?.logs ?? []}
                hydrating={hydrating}
                health={hydration?.health ?? null}
                verification={verification}
                negotiation={hydration?.negotiation ?? null}
                rollback={hydration?.rollback ?? null}
                executionMode={hydration?.executionMode ?? null}
                selectedPhase={selectedPhase}
                onClear={() => setSelectedPhase(null)}
              />
            </div>

            {/* Latest commit + events */}
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
              <div className="lg:col-span-7">
                <LatestCommitCard projectId={projectId} run={selected ?? null} isCanonical={isCanonical} />
              </div>
              <div className="lg:col-span-5">
                <EventsCard runId={selected?.deployment_id ?? null} logs={hydration?.logs ?? []} />
              </div>
            </div>

            {/* Repository intelligence + deployment health */}
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
              <div className="lg:col-span-6">
                <RepoIntelCard runId={selected?.deployment_id ?? null} detailHref={selected ? `/projects/${projectId}/runs/${selected.deployment_id}` : `/projects/${projectId}/orchestration`} />
              </div>
              <div id="deployment-health" className="scroll-mt-20 lg:col-span-6">
                <DeployHealthCard
                  run={selected ?? null}
                  health={hydration?.health ?? null}
                  runtimeLogs={hydration?.runtimeLogs ?? null}
                  detailHref={selected ? `/projects/${projectId}/runs/${selected.deployment_id}` : `/projects/${projectId}/runs`}
                />
              </div>
            </div>

            {/* Findings + recent runs */}
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
              <Panel
                id="findings"
                className="lg:col-span-7"
                title="Findings"
                eyebrow={findings.length > 0 ? `${findings.length} open · blockers first` : "Clear"}
              >
                <FindingsStrip findings={findings} />
              </Panel>
              <Panel
                className="lg:col-span-5"
                title="Recent runs"
                eyebrow={`${runs.length} recorded`}
                action={<Link href={`/projects/${projectId}/runs`} className="rounded text-[13px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">All executions →</Link>}
              >
                <ol className="divide-y divide-medha-border">
                  {runs.slice(0, 4).map((r) => (
                    <li key={r.deployment_id} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 py-2 text-[13px]">
                      <Badge tone={statusTone(r.status)}>{r.status.replace(/_/g, " ")}</Badge>
                      <Link href={`/projects/${projectId}/runs/${r.deployment_id}`} className="medha-mono min-w-0 truncate rounded font-medium text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">
                        {r.deployment_id.slice(0, 12)}…
                      </Link>
                      <span className="min-w-0 flex-1 truncate text-medha-tertiary">
                        {r.duration_seconds != null ? `${r.duration_seconds}s · ` : ""}{formatActivity(r.updated_at)}
                      </span>
                    </li>
                  ))}
                </ol>
              </Panel>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
