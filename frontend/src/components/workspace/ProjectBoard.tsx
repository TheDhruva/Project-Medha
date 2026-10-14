"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Info,
  Loader2,
  PlayCircle,
  Settings,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { MedhaFace, faceStateFromRun } from "@/components/medha/MedhaFace";
import { Badge, Breadcrumbs, EmptyState, ErrorBox, Panel, Skeleton } from "@/components/ui/primitives";
import { ExecutionModeBadge } from "@/components/ui/Section";
import { MetricCard } from "@/components/workspace/MetricCard";
import { PipelineTimeline } from "@/components/workspace/PipelineTimeline";
import { deriveFindings, deriveScorecards, type Finding } from "@/lib/projects/metrics";
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

function agentDot(state: string): string {
  if (state === "done") return "bg-medha-success";
  if (state === "active") return "bg-medha-run";
  if (state === "blocked") return "bg-medha-danger";
  return "bg-medha-border-strong";
}

const FINDING_STYLES: Record<Finding["tone"], { box: string; icon: string; Icon: typeof AlertTriangle }> = {
  error: { box: "border-medha-danger/30 bg-medha-danger-soft", icon: "text-medha-danger", Icon: AlertTriangle },
  warning: { box: "border-medha-warning/30 bg-medha-warning-soft", icon: "text-medha-warning", Icon: AlertTriangle },
  info: { box: "border-medha-run/25 bg-medha-run-soft", icon: "text-medha-run-ink", Icon: Info },
};

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

  const primaryAction = project ? (
    <button
      type="button"
      onClick={() => void startRun()}
      disabled={starting}
      className="inline-flex items-center gap-1.5 rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-medha-accent-hover disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
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
      <div className="mx-auto w-full max-w-[1200px] space-y-4">
        {/* Project identity, latest run status, target clarity, actions */}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <Breadcrumbs items={[{ label: "Projects", href: "/projects" }, { label: name }]} />
            <div className="mt-1 flex flex-wrap items-center gap-2.5">
              <h1 className="break-words text-[22px] font-bold leading-tight tracking-tight text-medha-text">{name}</h1>
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
                    size={26}
                  />
                  <Badge tone={statusTone(latest.status)}>{latest.status.replace(/_/g, " ")}</Badge>
                  {latest.is_demo ? <span className="text-[11px] font-semibold text-medha-tertiary">DEMO/MOCK</span> : null}
                </span>
              ) : null}
            </div>
            <p title={repo} className="medha-mono mt-0.5 truncate text-[12.5px] text-medha-secondary">{repo}</p>
            {project && !loading ? (
              <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[12.5px] text-medha-secondary">
                <span className="medha-label">Deploy target</span>
                <Link
                  href={`/projects/${projectId}/settings`}
                  className={cn(
                    "rounded font-semibold underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent",
                    project.deploy_target ? "text-medha-text" : "text-medha-warning",
                  )}
                >
                  {project.deploy_target ?? "None configured"} →
                </Link>
              </p>
            ) : null}
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Link
              href={`/verify${project ? `?project=${projectId}` : ""}`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-medha-border bg-medha-surface px-4 py-2 text-sm font-medium text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
            >
              Analyze changes
            </Link>
            <Link
              href={`/projects/${projectId}/settings`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-medha-border bg-medha-surface px-4 py-2 text-sm font-medium text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
            >
              <Settings className="h-4 w-4" aria-hidden /> Project settings
            </Link>
            {primaryAction}
          </div>
        </div>

        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}
        {startError ? (
          <p role="alert" className="rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3.5 py-2 text-[13px] font-medium text-medha-danger">
            {startError}
          </p>
        ) : null}

        {loading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Loading project">
            {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-36 w-full" />)}
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
            {/* Selected run — compact row with historical-run clarity */}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-medha-border bg-medha-surface px-3 py-2">
              <label htmlFor="board-run" className="medha-label shrink-0">Selected run</label>
              <select
                id="board-run"
                value={selected?.deployment_id ?? ""}
                onChange={(e) => selectRun(e.target.value)}
                className="min-w-0 max-w-full flex-1 rounded-md border border-medha-border bg-medha-surface px-2.5 py-1.5 text-sm text-medha-text focus:border-medha-accent focus:outline-none focus:ring-2 focus:ring-medha-accent/30"
              >
                {runs.map((r) => (
                  <option key={r.deployment_id} value={r.deployment_id}>
                    {r.deployment_id} · {r.status.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
              <ExecutionModeBadge mode={hydration?.executionMode} size="sm" />
              {selected && selected.is_demo ? (
                <span className="shrink-0 text-[11px] font-semibold text-medha-tertiary">DEMO/MOCK</span>
              ) : null}
              {selected ? (
                <span className="shrink-0 text-[12.5px] text-medha-tertiary">
                  {selected.duration_seconds != null ? `${selected.duration_seconds}s` : "duration —"} · {formatActivity(selected.updated_at)}
                </span>
              ) : null}
              {selected ? (
                <Link href={`/projects/${projectId}/runs/${selected.deployment_id}`} className="inline-flex shrink-0 items-center gap-1 rounded text-sm font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">
                  Open run detail <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                </Link>
              ) : null}
            </div>

            {/* Scorecards — every value evidence-backed or explicitly unassessed */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Run scorecards">
              {scorecards.map((metric) => (
                <MetricCard key={metric.id} metric={metric} />
              ))}
            </div>

            {/* Findings — most important current issue first */}
            <Panel
              title="Findings"
              eyebrow={findings.length > 0 ? `${findings.length} open` : "Clear"}
            >
              <div id="exec-notice" aria-label="Findings" className="space-y-2">
                {findings.length === 0 ? (
                  <p className="flex items-center gap-1.5 text-[13px] font-medium text-medha-success-ink">
                    <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden />
                    No outstanding issues for this run.
                  </p>
                ) : (
                  <ol className="space-y-2">
                    {findings.map((f, index) => {
                      const style = FINDING_STYLES[f.tone];
                      const { Icon } = style;
                      return (
                        <li key={f.id} className={cn("rounded-lg border px-3 py-2", style.box)}>
                          <div className="flex items-start gap-2">
                            <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", style.icon)} aria-hidden />
                            <div className="min-w-0 flex-1">
                              <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] font-semibold text-medha-text">
                                {f.title}
                                {index === 0 && findings.length > 1 ? (
                                  <span className="rounded-full border border-medha-border bg-medha-surface px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-medha-tertiary">
                                    Most important
                                  </span>
                                ) : null}
                              </p>
                              <p className="mt-0.5 break-words text-[12.5px] text-medha-secondary">{f.body}</p>
                              {f.note ? (
                                <p className="medha-label mt-1">{f.note}</p>
                              ) : null}
                              {f.nextActions && f.nextActions.length > 0 ? (
                                <ul className="mt-1 list-inside list-disc space-y-0.5 text-[12px] text-medha-secondary">
                                  {f.nextActions.map((action) => (
                                    <li key={action}>{action}</li>
                                  ))}
                                </ul>
                              ) : null}
                              {f.action ? (
                                <Link
                                  href={f.action.href}
                                  className="mt-1 inline-block rounded text-[12.5px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
                                >
                                  {f.action.label}
                                </Link>
                              ) : null}
                            </div>
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                )}
              </div>
            </Panel>

            <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
              <Panel
                className="lg:col-span-3"
                title="Execution pipeline"
                eyebrow={selected ? `${selected.deployment_id} · ${selected.current_stage ?? "no stage reported"}` : "Pipeline"}
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
                {hydration?.rollback ? (
                  <p className="mt-2.5 border-t border-medha-border pt-2 text-[13px] text-medha-secondary">
                    Rollback scope recorded — see <Link href={`/projects/${projectId}/graphs`} className="rounded font-medium text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">Graphs & Impact</Link> for preserved vs rolled-back services.
                  </p>
                ) : null}
              </Panel>

              <Panel
                className="lg:col-span-2"
                title="Agent activity"
                eyebrow="Observed from backend events"
                action={<Link href={`/projects/${projectId}/orchestration`} className="rounded text-[12px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">Activity →</Link>}
              >
                <ul className="grid grid-cols-1 gap-1">
                  {agents.map((a) => (
                    <li key={a.id} className="rounded-lg px-2 py-1 hover:bg-medha-surface-muted" title={a.detail}>
                      <span className="flex items-start gap-2 text-[13px]">
                        <span className={cn("status-dot mt-1.5 shrink-0", agentDot(a.state))} aria-hidden />
                        <span className="min-w-0">
                          <span className="font-medium text-medha-text">{a.label}</span>
                          <span className="text-medha-tertiary"> · {a.state}</span>
                          {a.state === "blocked" ? (
                            <span className="block truncate text-[11.5px] text-medha-danger" title={a.detail}>
                              {a.detail}
                            </span>
                          ) : null}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              </Panel>
            </div>

            <Panel
              title="Run history"
              eyebrow={`${runs.length} runs for this repository`}
              action={<Link href={`/projects/${projectId}/runs`} className="rounded text-[12px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">All executions →</Link>}
            >
              <ol className="divide-y divide-medha-border">
                {runs.slice(0, 5).map((r) => (
                  <li key={r.deployment_id} className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 py-2 text-[13px]">
                    <Badge tone={statusTone(r.status)}>{r.status.replace(/_/g, " ")}</Badge>
                    <Link href={`/projects/${projectId}/runs/${r.deployment_id}`} className="medha-mono min-w-0 truncate rounded font-medium text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">
                      {r.deployment_id}
                    </Link>
                    {r.error_code ? (
                      <span className="medha-mono rounded bg-medha-danger-soft px-1.5 py-0.5 text-[10.5px] font-semibold text-medha-danger" title={r.error_summary ?? r.error_code}>
                        {r.error_code}
                      </span>
                    ) : null}
                    <span className="min-w-0 flex-1 truncate text-medha-tertiary" title={`${r.is_demo ? "DEMO" : "LIVE"} · ${formatActivity(r.updated_at)}${r.error_summary ? ` · ${r.error_summary}` : ""}`}>
                      {r.is_demo ? "DEMO" : "LIVE"} · {r.duration_seconds != null ? `${r.duration_seconds}s · ` : ""}{formatActivity(r.updated_at)}
                      {r.error_summary ? ` · ${r.error_summary}` : ""}
                    </span>
                  </li>
                ))}
              </ol>
            </Panel>
          </>
        )}
      </div>
    </AppShell>
  );
}
