"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Loader2,
  PlayCircle,
  Settings,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { MedhaFace, faceStateFromRun } from "@/components/medha/MedhaFace";
import { Badge, EmptyState, ErrorBox, Panel, Skeleton } from "@/components/ui/primitives";
import { ExecutionModeBadge } from "@/components/ui/Section";
import { MetricCard } from "@/components/workspace/MetricCard";
import { PipelineTimeline } from "@/components/workspace/PipelineTimeline";
import {
  DeployHealthCard,
  EventsCard,
  FindingsStrip,
  LatestCommitCard,
  RepoIntelCard,
  deployStateOf,
} from "@/components/workspace/DashboardSections";
import { deriveFindings, deriveScorecards } from "@/lib/projects/metrics";
import {
  derivePipeline,
  resolveAgents,
  summarizeVerification,
  useProjectData,
} from "@/lib/projects/useProjectData";
import { formatActivity, isRunningStatus } from "@/lib/projects/projects";
import {
  createProjectRun,
  fetchConfigStatus,
  fetchScores,
  type ExecutionReadiness,
  type ScoresResponse,
} from "@/lib/api/client";
import { cn } from "@/lib/ui/cn";

/* A finished run reports completion only — never health. Only genuinely
   positive evidence (verification passed, preserved services) uses green. */
function statusTone(status: string): "success" | "warning" | "error" | "info" | "neutral" {
  if (status === "partial_recovery" || status === "awaiting_approval") return "warning";
  if (status === "failed" || status === "cancelled") return "error";
  if (isRunningStatus(status)) return "info";
  return "neutral";
}

function shortSha(v: string | null | undefined): string | null {
  if (!v) return null;
  return v.length > 12 ? v.slice(0, 7) : v;
}

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "runs", label: "Runs" },
  { id: "architecture", label: "Architecture" },
  { id: "deployments", label: "Deployments" },
  { id: "settings", label: "Settings" },
] as const;

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

  const selected = useMemo(
    () => runs.find((r) => r.deployment_id === selectedId) ?? latest,
    [runs, selectedId, latest],
  );
  const verification = useMemo(
    () => summarizeVerification(hydration?.verification ?? null),
    [hydration],
  );
  const agents = useMemo(
    () => (hydration ? resolveAgents(hydration, selected?.current_stage ?? null, selected?.status ?? null).agents : []),
    [hydration, selected],
  );
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

  const configBlocked = pipeline.some((s) => s.state === "blocked" && s.reason === "config");
  const running = selected ? isRunningStatus(selected.status) : false;
  const deploy = deployStateOf(selected ?? null, hydration?.health ?? null);
  const blockers = findings.filter((f) => f.tone === "error").length;
  const lastCompleted = useMemo(
    () => runs.find((r) => r.status === "completed") ?? null,
    [runs],
  );
  const failingStage = useMemo(() => pipeline.find((s) => s.state === "blocked") ?? null, [pipeline]);
  const isCanonical = projectId.startsWith("prj_");

  // Score snapshots for the selected run (404/failure → honest "not assessed").
  useEffect(() => {
    if (!selectedId) {
      setScores(null);
      return;
    }
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
          className="inline-flex items-center gap-1.5 rounded-lg border border-medha-run/25 bg-medha-run-soft px-3 py-2 text-[13px] font-semibold text-medha-run-ink transition hover:brightness-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
        >
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          View active run
        </Link>
      ) : null}
      {(pendingApprovals.length > 0 || selected?.status === "awaiting_approval") && !activeRunHref ? (
        <Link
          href={`/projects/${projectId}/changes`}
          className="inline-flex items-center gap-1.5 rounded-lg border border-medha-border bg-medha-surface px-3 py-2 text-[13px] font-medium text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
        >
          Review plan ({pendingApprovals.length || 1})
        </Link>
      ) : null}
      {selected?.status === "failed" && runHref ? (
        <Link
          href={runHref}
          className="inline-flex items-center gap-1.5 rounded-lg border border-medha-border bg-medha-surface px-3 py-2 text-[13px] font-medium text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
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

  const tabHref = (id: string): string => {
    switch (id) {
      case "runs": return `/projects/${projectId}/runs`;
      case "architecture": return `/projects/${projectId}/graphs`;
      case "deployments": return selected ? `/projects/${projectId}/runs/${selected.deployment_id}` : `/projects/${projectId}/runs`;
      case "settings": return `/projects/${projectId}/settings`;
      default: return `/projects/${projectId}`;
    }
  };

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-[1280px] space-y-3">
        {/* ---- Compact project header + operational status ---- */}
        <div className="rounded-lg border border-medha-border bg-medha-surface px-4 py-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="break-words text-[19px] font-bold leading-tight tracking-tight text-medha-text">{name}</h1>
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
                    {latest.is_demo ? <span className="text-[11px] font-semibold text-medha-tertiary">DEMO/MOCK</span> : null}
                  </span>
                ) : null}
              </div>
              <p title={repo} className="medha-mono mt-0.5 truncate text-[12px] text-medha-secondary">
                {repo}{project?.branch ? ` · ${project.branch}` : ""}
              </p>
              {selected && !loading ? (
                <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-medha-secondary">
                  <div className="flex gap-1.5">
                    <dt className="text-medha-tertiary">Run</dt>
                    <dd className="medha-mono font-medium text-medha-text">{selected.deployment_id.slice(0, 12)}…</dd>
                  </div>
                  <div className="flex gap-1.5">
                    <dt className="text-medha-tertiary">Revision</dt>
                    <dd className="medha-mono font-medium text-medha-text">{shortSha(selected.target_revision) ?? "—"}</dd>
                  </div>
                  <div className="flex gap-1.5">
                    <dt className="text-medha-tertiary">Pipeline</dt>
                    <dd className="font-medium text-medha-text">{selected.current_stage ?? selected.status.replace(/_/g, " ")}</dd>
                  </div>
                  <div className="flex gap-1.5">
                    <dt className="text-medha-tertiary">Deployment</dt>
                    <dd className={cn("font-medium", deploy.tone === "success" ? "text-medha-success-ink" : deploy.tone === "error" ? "text-medha-danger" : "text-medha-text")}>
                      {deploy.label}
                    </dd>
                  </div>
                  {lastCompleted ? (
                    <div className="flex gap-1.5">
                      <dt className="text-medha-tertiary">Last completed</dt>
                      <dd className="font-medium text-medha-text">{formatActivity(lastCompleted.updated_at)}</dd>
                    </div>
                  ) : null}
                  {blockers > 0 ? (
                    <div className="flex gap-1.5">
                      <dt className="text-medha-tertiary">Blockers</dt>
                      <dd className="font-semibold text-medha-danger">{blockers}</dd>
                    </div>
                  ) : null}
                </dl>
              ) : null}
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {secondaryActions}
              <Link
                href={`/projects/${projectId}/settings`}
                className="inline-flex items-center gap-1.5 rounded-lg border border-medha-border bg-medha-surface px-3 py-2 text-[13px] font-medium text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
              >
                <Settings className="h-4 w-4" aria-hidden /> Settings
              </Link>
              {primaryAction}
            </div>
          </div>
          {/* Secondary navigation — existing routes, no duplicate destinations */}
          <nav aria-label="Project sections" className="mt-2.5 flex flex-wrap gap-1 border-t border-medha-border pt-2">
            {TABS.map((t) => (
              <Link
                key={t.id}
                href={tabHref(t.id)}
                aria-current={t.id === "overview" ? "page" : undefined}
                className={cn(
                  "rounded-md px-2.5 py-1 text-[12.5px] font-medium transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent",
                  t.id === "overview"
                    ? "bg-medha-text text-white"
                    : "text-medha-secondary hover:bg-medha-surface-muted hover:text-medha-text",
                )}
              >
                {t.label}
              </Link>
            ))}
          </nav>
        </div>

        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}
        {startError ? (
          <p role="alert" className="rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3.5 py-2 text-[13px] font-medium text-medha-danger">
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
            {/* Run selector — compact */}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-medha-border bg-medha-surface px-3 py-1.5">
              <label htmlFor="board-run" className="medha-label shrink-0">Run</label>
              <select
                id="board-run"
                value={selected?.deployment_id ?? ""}
                onChange={(e) => selectRun(e.target.value)}
                className="min-w-0 max-w-full flex-1 rounded-md border border-medha-border bg-medha-surface px-2 py-1 text-[13px] text-medha-text focus:border-medha-accent focus:outline-none focus:ring-2 focus:ring-medha-accent/30"
              >
                {runs.map((r) => (
                  <option key={r.deployment_id} value={r.deployment_id}>
                    {r.deployment_id.slice(0, 12)}… · {r.status.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
              <ExecutionModeBadge mode={hydration?.executionMode} size="sm" />
              {selected ? (
                <span className="shrink-0 text-[12px] text-medha-tertiary">
                  {selected.duration_seconds != null ? `${selected.duration_seconds}s · ` : ""}{formatActivity(selected.updated_at)}
                </span>
              ) : null}
              {selected ? (
                <Link href={`/projects/${projectId}/runs/${selected.deployment_id}`} className="inline-flex shrink-0 items-center gap-1 rounded text-[13px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">
                  Open run <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                </Link>
              ) : null}
            </div>

            {/* Four semicircular assessment cards */}
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4" aria-label="Run scorecards">
              {scorecards.map((metric) => (
                <MetricCard key={metric.id} metric={metric} />
              ))}
            </div>

            {/* Pipeline + operational status */}
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
              <Panel
                className="lg:col-span-7"
                title="Execution pipeline"
                eyebrow={selected ? `${selected.deployment_id.slice(0, 12)}… · ${selected.current_stage ?? "no stage reported"}` : "Pipeline"}
                action={<Link href={`/projects/${projectId}/runs`} className="rounded text-[12px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">All executions →</Link>}
              >
                <PipelineTimeline
                  stages={pipeline}
                  running={running}
                  blockedHint={
                    configBlocked && selected
                      ? `Execution was not attempted (${selected.error_code ?? "execution not configured"}). Analysis and verification completed and remain valid — configure execution in Settings.`
                      : null
                  }
                />
                {selected?.status === "failed" ? (
                  <p className="mt-2 border-t border-medha-border pt-2 text-[12.5px] text-medha-secondary">
                    {failingStage ? <>Failed at <span className="font-semibold text-medha-danger">{failingStage.label}</span>{selected.error_summary ? ` — ${selected.error_summary}` : ""} </> : (selected.error_summary ?? "Run failed. ")}
                    {runHref ? <Link href={runHref} className="rounded font-semibold text-medha-accent hover:underline">Error details →</Link> : null}
                  </p>
                ) : selected?.status === "completed" ? (
                  <p className="mt-2 border-t border-medha-border pt-2 text-[12.5px] text-medha-secondary">
                    Execution completed{hydration?.health?.health_status === "healthy" ? " and application health confirmed." : " — application health " + (hydration?.health ? "reported separately." : "not yet confirmed.")}
                  </p>
                ) : null}
                {hydration?.rollback ? (
                  <p className="mt-1.5 text-[12.5px] text-medha-secondary">
                    Rollback scope recorded — see <Link href={`/projects/${projectId}/graphs`} className="rounded font-medium text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">Graphs & Impact</Link> for preserved vs rolled-back services.
                  </p>
                ) : null}
              </Panel>

              <Panel
                className="lg:col-span-5"
                title="Operational status"
                eyebrow="Pipeline vs deployment, kept separate"
                action={<Link href={`/projects/${projectId}/orchestration`} className="rounded text-[12px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">Activity →</Link>}
              >
                <dl className="space-y-1.5 text-[12.5px]">
                  <div className="flex gap-2"><dt className="w-24 shrink-0 text-medha-tertiary">Pipeline</dt><dd className="font-medium text-medha-text">{selected ? selected.status.replace(/_/g, " ") : "—"}{selected?.current_stage ? ` · ${selected.current_stage}` : ""}</dd></div>
                  <div className="flex gap-2"><dt className="w-24 shrink-0 text-medha-tertiary">Deployment</dt><dd className="font-medium text-medha-text">{deploy.label}</dd></div>
                  <div className="flex gap-2">
                    <dt className="w-24 shrink-0 text-medha-tertiary">Verification</dt>
                    <dd className="text-medha-text">
                      {verification ? (
                        verification.total > 0
                          ? `${verification.passed === true ? "Passed" : verification.passed === false ? "Failed" : "Inconclusive"} · ${verification.total} checks`
                          : "No checks recorded"
                      ) : hydrating ? "Loading…" : "No artifact yet"}
                      {" · "}<Link href={`/projects/${projectId}/verification`} className="rounded font-medium text-medha-accent hover:underline">details</Link>
                    </dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-24 shrink-0 text-medha-tertiary">Negotiation</dt>
                    <dd className="text-medha-text">
                      {hydration?.negotiation ? `${hydration.negotiation.status} · round ${hydration.negotiation.round}/${hydration.negotiation.maxRounds}` : hydrating ? "Loading…" : "No CNP artifact"}
                      {" · "}<Link href={`/projects/${projectId}/constraints`} className="rounded font-medium text-medha-accent hover:underline">constraints</Link>
                    </dd>
                  </div>
                  {pendingApprovals.length > 0 ? (
                    <div className="flex gap-2"><dt className="w-24 shrink-0 text-medha-tertiary">Approvals</dt><dd><Link href={`/projects/${projectId}/changes`} className="rounded font-medium text-medha-accent hover:underline">{pendingApprovals.length} awaiting decision →</Link></dd></div>
                  ) : null}
                </dl>
                {agents.length > 0 ? (
                  <ul className="mt-2 grid grid-cols-1 gap-0.5 border-t border-medha-border pt-2">
                    {agents.filter((a) => a.state !== "idle").slice(0, 4).map((a) => (
                      <li key={a.id} className="flex items-center gap-2 text-[12px]" title={a.detail}>
                        <span className={cn("status-dot", a.state === "done" ? "bg-medha-success" : a.state === "active" ? "bg-medha-run medha-stage-pulse" : "bg-medha-danger")} aria-hidden />
                        <span className="font-medium text-medha-text">{a.label}</span>
                        <span className="truncate text-medha-tertiary">· {a.state}</span>
                      </li>
                    ))}
                    {agents.every((a) => a.state === "idle") ? (
                      <li className="text-[12px] text-medha-tertiary">No agent activity observed for this run.</li>
                    ) : null}
                  </ul>
                ) : null}
              </Panel>
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
              <div className="lg:col-span-6">
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
                action={<Link href={`/projects/${projectId}/runs`} className="rounded text-[12px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">All executions →</Link>}
              >
                <ol className="divide-y divide-medha-border">
                  {runs.slice(0, 4).map((r) => (
                    <li key={r.deployment_id} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 py-1.5 text-[12.5px]">
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
