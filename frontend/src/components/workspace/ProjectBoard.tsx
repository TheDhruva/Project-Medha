"use client";

import Link from "next/link";
import { useMemo } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, PlayCircle, XCircle } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Badge, Breadcrumbs, DemoBadge, EmptyState, ErrorBox, PageHeader, Panel, Skeleton } from "@/components/ui/primitives";
import {
  deriveAgentsFromLogs,
  derivePipeline,
  summarizeVerification,
  useProjectData,
} from "@/lib/projects/useProjectData";
import { formatActivity, isRunningStatus } from "@/lib/projects/projects";
import { cn } from "@/lib/ui/cn";

function statusTone(status: string): "success" | "warning" | "error" | "info" | "neutral" {
  if (status === "completed") return "success";
  if (status === "partial_recovery" || status === "awaiting_approval") return "warning";
  if (status === "failed" || status === "cancelled") return "error";
  if (isRunningStatus(status)) return "info";
  return "neutral";
}

function agentDot(state: string): string {
  if (state === "done") return "bg-medha-success";
  if (state === "active") return "bg-medha-run animate-medha-pulse";
  if (state === "blocked") return "bg-medha-danger";
  return "bg-medha-border-strong";
}

export function ProjectBoard({ projectId }: { projectId: string }) {
  const {
    repo, name, runs, loading, error, backendReachable,
    latest, selectedId, selectRun, hydration, hydrating, proposals, refresh,
  } = useProjectData(projectId);

  const selected = useMemo(
    () => runs.find((r) => r.deployment_id === selectedId) ?? latest,
    [runs, selectedId, latest],
  );
  const verification = useMemo(
    () => summarizeVerification(hydration?.verification ?? null),
    [hydration],
  );
  const agents = useMemo(
    () => (hydration ? deriveAgentsFromLogs(hydration.logs, selected?.current_stage ?? null, selected?.status ?? null) : []),
    [hydration, selected],
  );
  const pipeline = useMemo(
    () => (hydration ? derivePipeline(hydration.logs, selected?.current_stage ?? null, selected?.status ?? null) : []),
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
  const attention = useMemo(() => {
    const items: string[] = [];
    if (selected?.status === "failed") items.push(selected.error_summary || "Selected run failed.");
    if (selected?.status === "awaiting_approval") items.push("Plan is awaiting human approval.");
    if (selected?.status === "partial_recovery") items.push("Recovered with scoped rollback — confirm preserved services.");
    if (verification && verification.passed === false) items.push("Verification gate failed — execution blocked.");
    if (conflicts.length > 0 && hydration?.negotiation?.status !== "resolved") {
      items.push(`${conflicts.length} unresolved constraint conflict${conflicts.length === 1 ? "" : "s"}.`);
    }
    return items;
  }, [selected, verification, conflicts, hydration]);

  if (!repo) {
    return (
      <AppShell>
        <EmptyState
          title="Project not found"
          body="This project link does not decode to a known repository. Projects are keyed by repository URL."
          action={<Link href="/" className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white">Back to hub</Link>}
        />
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="space-y-4">
        <PageHeader
          title={name}
          subtitle={repo}
          breadcrumbs={<Breadcrumbs items={[{ label: "Projects", href: "/" }, { label: name }]} />}
          actions={
            <>
              {selected ? <DemoBadge isDemo={selected.is_demo} /> : null}
              <Link href="/verify" className="inline-flex items-center gap-1.5 rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white hover:bg-medha-accent-hover">
                <PlayCircle className="h-4 w-4" aria-hidden /> New run
              </Link>
            </>
          }
        />

        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}

        {loading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Loading project">
            {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-36 w-full" />)}
          </div>
        ) : runs.length === 0 ? (
          <EmptyState
            title="No runs recorded for this repository"
            body="Start the first run to populate status, verification, conflicts, and evidence — from the demo engine or the real local pipeline."
            action={<Link href="/verify" className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white">Start first run</Link>}
          />
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor="board-run" className="medha-label">Selected run</label>
              <select
                id="board-run"
                value={selected?.deployment_id ?? ""}
                onChange={(e) => selectRun(e.target.value)}
                className="max-w-full rounded-lg border border-medha-border bg-white px-3 py-1.5 text-sm text-medha-text"
              >
                {runs.map((r) => (
                  <option key={r.deployment_id} value={r.deployment_id}>
                    {r.deployment_id} · {r.status}{r.is_demo ? " · DEMO" : " · LIVE"}
                  </option>
                ))}
              </select>
              {selected ? (
                <Link href={`/projects/${projectId}/runs/${selected.deployment_id}`} className="inline-flex items-center gap-1 text-sm font-semibold text-medha-accent hover:underline">
                  Open run detail <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                </Link>
              ) : null}
            </div>

            {attention.length > 0 ? (
              <ul className="space-y-1.5" aria-label="Attention items">
                {attention.map((a) => (
                  <li key={a} className="flex items-start gap-2 rounded-xl border border-medha-danger/30 bg-medha-danger-soft px-3.5 py-2 text-[13px] font-medium text-medha-danger">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> {a}
                  </li>
                ))}
              </ul>
            ) : null}

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Panel title="Project status" eyebrow="Latest observed state">
                {selected ? (
                  <dl className="space-y-1.5 text-[13px]">
                    <div className="flex items-center gap-2">
                      <Badge tone={statusTone(selected.status)}>{selected.status.replace(/_/g, " ")}</Badge>
                      {selected.is_demo ? <span className="text-[11px] font-semibold text-medha-tertiary">DEMO/MOCK</span> : null}
                    </div>
                    <div className="flex gap-2"><dt className="w-20 shrink-0 text-medha-tertiary">Scenario</dt><dd className="text-medha-text">{selected.scenario ?? "—"}</dd></div>
                    <div className="flex gap-2"><dt className="w-20 shrink-0 text-medha-tertiary">Duration</dt><dd className="text-medha-text">{selected.duration_seconds != null ? `${selected.duration_seconds}s` : "—"}</dd></div>
                    <div className="flex gap-2"><dt className="w-20 shrink-0 text-medha-tertiary">Updated</dt><dd className="text-medha-text">{formatActivity(selected.updated_at)}</dd></div>
                    {selected.error_summary ? <p className="text-medha-danger">{selected.error_summary}</p> : null}
                  </dl>
                ) : <p className="text-sm text-medha-secondary">No run selected.</p>}
              </Panel>

              <Panel
                title="Verification"
                eyebrow={hydrating ? "Loading…" : verification ? `${verification.total} checks` : "No artifact"}
                action={<Link href={`/projects/${projectId}/verification`} className="text-[12px] font-semibold text-medha-accent hover:underline">Details →</Link>}
              >
                {!hydration || hydrating ? (
                  <p className="text-[13px] text-medha-secondary">Loading verification artifact…</p>
                ) : !verification ? (
                  <p className="text-[13px] text-medha-secondary">No verification artifact for this run yet — it may not have reached the verify stage.</p>
                ) : (
                  <div className="space-y-1.5 text-[13px]">
                    <p className="flex items-center gap-1.5 font-semibold text-medha-text">
                      {verification.passed === true ? <CheckCircle2 className="h-4 w-4 text-medha-success" aria-hidden /> : null}
                      {verification.passed === false ? <XCircle className="h-4 w-4 text-medha-danger" aria-hidden /> : null}
                      {verification.passed === true ? "Passed" : verification.passed === false ? `Failed (${verification.failed}/${verification.total})` : "No conclusive result"}
                      {verification.score != null ? <span className="font-normal text-medha-secondary">· score {verification.score}</span> : null}
                    </p>
                    {verification.summary ? <p className="text-medha-secondary">{verification.summary}</p> : null}
                    {verification.blocking.slice(0, 2).map((b) => (
                      <p key={b} className="text-medha-danger">{b}</p>
                    ))}
                  </div>
                )}
              </Panel>

              <Panel
                title="Conflicts"
                eyebrow={hydration?.negotiation ? `CNP · ${hydration.negotiation.status}` : "CNP"}
                action={<Link href={`/projects/${projectId}/orchestration`} className="text-[12px] font-semibold text-medha-accent hover:underline">Negotiation →</Link>}
              >
                {!hydration || hydrating ? (
                  <p className="text-[13px] text-medha-secondary">Loading constraints…</p>
                ) : hydration.constraints.length === 0 ? (
                  <p className="text-[13px] text-medha-secondary">No constraints observed for this run yet.</p>
                ) : (
                  <div className="space-y-1.5 text-[13px]">
                    <p className="text-medha-text">
                      <span className="font-semibold">{hydration.constraints.length}</span> constraints ·{" "}
                      <span className={cn("font-semibold", conflicts.length > 0 ? "text-medha-danger" : "text-medha-success")}>
                        {conflicts.length} conflicting
                      </span>
                    </p>
                    {hydration.negotiation?.resolution ? <p className="text-medha-secondary">{hydration.negotiation.resolution}</p> : null}
                    {hydration.negotiation?.method ? <p className="text-medha-secondary">Method: {hydration.negotiation.method}</p> : null}
                  </div>
                )}
              </Panel>

              <Panel
                title="Pending approvals"
                eyebrow={`${pendingApprovals.length} open`}
                action={<Link href={`/projects/${projectId}/changes`} className="text-[12px] font-semibold text-medha-accent hover:underline">Review →</Link>}
              >
                {pendingApprovals.length === 0 ? (
                  <p className="text-[13px] text-medha-secondary">No proposals awaiting a decision for this repository.</p>
                ) : (
                  <ul className="space-y-1.5">
                    {pendingApprovals.slice(0, 3).map((p) => (
                      <li key={p.proposal_id} className="rounded-lg border border-medha-warning/40 bg-medha-warning-soft px-2.5 py-1.5 text-[12px]">
                        <p className="medha-mono truncate font-medium text-medha-text">{p.proposal_id}</p>
                        <p className="truncate text-medha-secondary">{p.branch} · {p.target_sha.slice(0, 8)}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </div>

            <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
              <Panel
                className="lg:col-span-3"
                title="Execution pipeline"
                eyebrow={selected ? `${selected.deployment_id} · ${selected.current_stage ?? "no stage reported"}` : "Pipeline"}
                action={<Link href={`/projects/${projectId}/runs`} className="text-[12px] font-semibold text-medha-accent hover:underline">All executions →</Link>}
              >
                <ol className="flex flex-wrap items-center gap-1.5" aria-label="Pipeline stages">
                  {pipeline.map((s, i) => (
                    <li key={s.id} className="flex items-center gap-1.5">
                      {i > 0 ? <span aria-hidden className="text-medha-border-strong">→</span> : null}
                      <span
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-medium",
                          s.state === "done" && "border-medha-success/30 bg-medha-success-soft text-medha-success",
                          s.state === "active" && "border-medha-run/25 bg-medha-run-soft text-medha-run-ink",
                          s.state === "blocked" && "border-medha-danger/30 bg-medha-danger-soft text-medha-danger",
                          s.state === "idle" && "border-medha-border bg-white text-medha-tertiary",
                        )}
                      >
                        <span className={cn("status-dot", s.state === "done" ? "bg-medha-success" : s.state === "active" ? "bg-medha-run animate-medha-pulse" : s.state === "blocked" ? "bg-medha-danger" : "bg-medha-border-strong")} aria-hidden />
                        {s.label}
                      </span>
                    </li>
                  ))}
                </ol>
                {hydration?.rollback ? (
                  <p className="mt-2 text-[13px] text-medha-secondary">
                    Rollback scope recorded — see <Link href={`/projects/${projectId}/graphs`} className="font-medium text-medha-accent hover:underline">Graphs & Impact</Link> for preserved vs rolled-back services.
                  </p>
                ) : null}
              </Panel>

              <Panel
                className="lg:col-span-2"
                title="Active agents"
                eyebrow="Observed from backend events"
                action={<Link href={`/projects/${projectId}/orchestration`} className="text-[12px] font-semibold text-medha-accent hover:underline">Activity →</Link>}
              >
                <ul className="grid max-h-44 grid-cols-1 gap-1 overflow-y-auto">
                  {agents.map((a) => (
                    <li key={a.id} className="flex items-start gap-2 rounded-lg px-2 py-1 text-[13px] hover:bg-medha-muted/50" title={a.detail}>
                      <span className={cn("status-dot mt-1.5", agentDot(a.state))} aria-hidden />
                      <span className="min-w-0">
                        <span className="font-medium text-medha-text">{a.label}</span>
                        <span className="text-medha-tertiary"> · {a.state}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </Panel>
            </div>

            <Panel
              title="Recent activity"
              eyebrow={`${runs.length} runs for this repository`}
              action={<Link href={`/projects/${projectId}/runs`} className="text-[12px] font-semibold text-medha-accent hover:underline">All executions →</Link>}
            >
              <ol className="divide-y divide-medha-border">
                {runs.slice(0, 5).map((r) => (
                  <li key={r.deployment_id} className="flex flex-wrap items-center gap-2 py-2 text-[13px]">
                    <Badge tone={statusTone(r.status)}>{r.status.replace(/_/g, " ")}</Badge>
                    <Link href={`/projects/${projectId}/runs/${r.deployment_id}`} className="medha-mono font-medium text-medha-accent hover:underline">
                      {r.deployment_id}
                    </Link>
                    <span className="text-medha-tertiary">
                      {r.is_demo ? "DEMO" : "LIVE"} · {formatActivity(r.updated_at)}
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
