"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowLeft, CheckCircle2, XCircle } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { RunDetailView } from "@/components/run/RunDetailNew";
// CommitGraph pulls @xyflow: code-split so project pages paint without it.
const CommitGraph = dynamic(
  () => import("@/components/history/CommitGraph").then((m) => m.CommitGraph),
  { ssr: false, loading: () => null },
);
import { ScoresPanel } from "@/components/scores/ScoresPanel";
import {
  Badge, Breadcrumbs, Button, DemoBadge, Dialog, EmptyState, ErrorBox,
  PageHeader, Panel, Skeleton,
} from "@/components/ui/primitives";
import { decideProposal } from "@/lib/api/client";
import {
  derivePipeline, resolveAgents, summarizeVerification,
  useProjectData,
} from "@/lib/projects/useProjectData";
import { formatActivity, isRunningStatus } from "@/lib/projects/projects";
import { cn } from "@/lib/ui/cn";

/* ================= shared ================= */

function crumbs(projectId: string, name: string, tail: string) {
  return <Breadcrumbs items={[{ label: "Projects", href: "/projects" }, { label: name, href: `/projects/${projectId}` }, { label: tail }]} />;
}

function NotFound({ what }: { what: string }) {
  return (
    <AppShell>
      <EmptyState
        title="Project not found"
        body={what}
        action={<Link href="/projects" className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white">Back to projects</Link>}
      />
    </AppShell>
  );
}

function RunPicker({ projectId, runIds, value, onChange, statuses }: {
  projectId: string;
  runIds: { id: string; label: string }[];
  value: string;
  onChange: (id: string) => void;
  statuses: Record<string, string>;
}) {
  if (runIds.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor={`run-picker-${projectId}`} className="medha-label">Run</label>
      <select
        id={`run-picker-${projectId}`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="max-w-full rounded-lg border border-medha-border bg-white px-3 py-1.5 text-sm text-medha-text"
      >
        {runIds.map((r) => (
          <option key={r.id} value={r.id}>{r.label} · {statuses[r.id] ?? ""}</option>
        ))}
      </select>
      <Link href={`/projects/${projectId}/runs/${value}`} className="text-[13px] font-semibold text-medha-accent hover:underline">
        Open run detail →
      </Link>
    </div>
  );
}

function proposalBadge(status: string) {
  switch (status) {
    case "ready": return <Badge tone="info">Ready for review</Badge>;
    case "pending": return <Badge tone="neutral">Pending analysis</Badge>;
    case "approved": return <Badge tone="success">Approved</Badge>;
    case "executed": return <Badge tone="success">Executed</Badge>;
    case "executing": return <Badge tone="info">Executing</Badge>;
    case "rejected": return <Badge tone="error">Rejected</Badge>;
    case "stale": return <Badge tone="error">Stale</Badge>;
    default: return <Badge tone="neutral">{status}</Badge>;
  }
}

function checkBadge(status: string) {
  if (status === "pass") return <Badge tone="success">Pass</Badge>;
  if (status === "fail") return <Badge tone="error">Fail</Badge>;
  if (status === "warn" || status === "warning") return <Badge tone="warning">Warning</Badge>;
  return <Badge tone="neutral">{status || "unknown"}</Badge>;
}

function LoadingGrid() {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2" aria-label="Loading">
      {[0, 1].map((i) => <Skeleton key={i} className="h-40 w-full" />)}
    </div>
  );
}

/* ================= CHANGES LIST ================= */

export function ChangesList({ projectId }: { projectId: string }) {
  const { repo, name, proposals, proposalsLoading, loading, error, backendReachable, refresh } = useProjectData(projectId);
  if (!repo) return <NotFound what="This project link does not decode to a known repository." />;

  const open = proposals.filter((p) => p.status === "ready" || p.status === "pending");
  const decided = proposals.filter((p) => p.status !== "ready" && p.status !== "pending");

  return (
    <AppShell>
      <div className="space-y-5">
        <PageHeader
          title="Changes & Reviews"
          subtitle="Push-triggered approval proposals for this repository. Approval binds to one exact plan hash — anything else fails closed as stale."
          breadcrumbs={crumbs(projectId, name, "Changes")}
          actions={<Button variant="secondary" onClick={() => refresh()}>Refresh</Button>}
        />
        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}
        {loading || proposalsLoading ? <LoadingGrid /> : proposals.length === 0 ? (
          <EmptyState
            title="No proposals for this repository"
            body="Proposals appear here when the GitHub webhook receives a push to a watched branch. Global proposals live under Proposals."
            action={<Link href="/proposals" className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white">All proposals</Link>}
          />
        ) : (
          <>
            {open.length > 0 ? (
              <p role="status" className="rounded-xl border border-medha-warning/30 bg-medha-warning-soft px-4 py-2.5 text-sm font-medium text-medha-warning">
                {open.length} proposal{open.length === 1 ? "" : "s"} awaiting a decision.
              </p>
            ) : null}
            <ul className="space-y-3">
              {[...open, ...decided].map((p) => (
                <li key={p.proposal_id} className="medha-panel p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="medha-mono text-[14px] font-semibold text-medha-text">{p.proposal_id}</h2>
                        {proposalBadge(p.status)}
                      </div>
                      <p className="medha-mono mt-1 text-[12px] text-medha-secondary">
                        {p.branch} · {(p.target_sha ?? "").slice(0, 12)}
                        {p.plan_hash ? ` · plan ${p.plan_hash.slice(0, 12)}` : ""}
                      </p>
                      <p className="mt-1 text-[13px] text-medha-secondary">
                        Created {formatActivity(p.created_at)}
                        {p.decided_by ? ` · decided by ${p.decided_by}` : ""}
                        {p.deployment_id ? (
                          <> · analysis <Link href={`/projects/${projectId}/runs/${p.deployment_id}`} className="medha-mono text-medha-accent hover:underline">{p.deployment_id}</Link></>
                        ) : null}
                      </p>
                    </div>
                    <Link href={`/projects/${projectId}/changes/${encodeURIComponent(p.proposal_id)}`} className="rounded-lg bg-medha-accent px-3.5 py-2 text-sm font-semibold text-white hover:bg-medha-accent-hover">
                      Review proposal
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </AppShell>
  );
}

/* ================= CHANGE REVIEW ================= */

export function ChangeReview({ projectId, proposalId }: { projectId: string; proposalId: string }) {
  const { repo, name, proposals, proposalsLoading, loading, refresh } = useProjectData(projectId);
  const [reason, setReason] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const proposal = useMemo(
    () => proposals.find((p) => p.proposal_id === proposalId) ?? null,
    [proposals, proposalId],
  );
  if (!repo) return <NotFound what="This project link does not decode to a known repository." />;
  if (!loading && !proposalsLoading && !proposal) {
    return (
      <AppShell>
        <EmptyState
          title="Proposal not found"
          body={`No proposal ${proposalId} belongs to this repository. It may belong to another project or have been pruned.`}
          action={<Link href={`/projects/${projectId}/changes`} className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white">Back to changes</Link>}
        />
      </AppShell>
    );
  }

  async function act(decision: "approve" | "reject") {
    if (!proposal) return;
    setBusy(true);
    setFeedback(null);
    try {
      const result = await decideProposal(proposal.proposal_id, decision, reason.trim() || undefined);
      setFeedback(
        decision === "approve"
          ? `Approved — execution ${result.execution_id ?? "started"}${result.duplicate ? " (duplicate request, not executed twice)" : ""}.`
          : "Rejected. The proposal stays inspectable; nothing executes.",
      );
      refresh();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Decision failed.");
    } finally {
      setBusy(false);
    }
  }

  const approvable = proposal?.status === "ready";

  return (
    <AppShell>
      <div className="space-y-5">
        <Link href={`/projects/${projectId}/changes`} className="inline-flex items-center gap-1 text-sm text-medha-secondary hover:text-medha-text">
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> All changes
        </Link>
        <PageHeader
          title={proposal ? `Proposal ${proposal.proposal_id}` : "Review proposal"}
          subtitle={proposal ? `${proposal.repository} · ${proposal.branch} → ${(proposal.target_sha ?? "").slice(0, 12)}` : undefined}
          breadcrumbs={crumbs(projectId, name, "Review")}
          actions={proposal ? proposalBadge(proposal.status) : undefined}
        />
        {loading || proposalsLoading || !proposal ? <LoadingGrid /> : (
          <>
            {feedback ? <p role="status" className="rounded-xl border border-medha-run/25 bg-medha-run-soft px-4 py-2.5 text-sm text-medha-run-ink">{feedback}</p> : null}
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <Panel title="Plan identity" eyebrow="What approval binds to">
                <dl className="space-y-1.5 text-[13px]">
                  <div className="flex gap-2"><dt className="w-28 shrink-0 text-medha-tertiary">Plan hash</dt><dd className="medha-mono break-all text-medha-text">{proposal.plan_hash ?? "—"}</dd></div>
                  <div className="flex gap-2"><dt className="w-28 shrink-0 text-medha-tertiary">Base SHA</dt><dd className="medha-mono text-medha-text">{proposal.base_sha ?? "—"}</dd></div>
                  <div className="flex gap-2"><dt className="w-28 shrink-0 text-medha-tertiary">Target SHA</dt><dd className="medha-mono text-medha-text">{proposal.target_sha}</dd></div>
                  <div className="flex gap-2"><dt className="w-28 shrink-0 text-medha-tertiary">Created by</dt><dd className="text-medha-text">{proposal.created_by ?? "webhook"}</dd></div>
                  <div className="flex gap-2"><dt className="w-28 shrink-0 text-medha-tertiary">Created</dt><dd className="text-medha-text">{formatActivity(proposal.created_at)}</dd></div>
                  {proposal.deployment_id ? (
                    <div className="flex gap-2"><dt className="w-28 shrink-0 text-medha-tertiary">Analysis</dt><dd><Link href={`/projects/${projectId}/runs/${proposal.deployment_id}`} className="medha-mono text-medha-accent hover:underline">{proposal.deployment_id}</Link></dd></div>
                  ) : null}
                </dl>
                {proposal.plan ? (
                  <details className="mt-3">
                    <summary className="cursor-pointer text-[13px] font-semibold text-medha-accent">Inspect plan JSON</summary>
                    <pre className="medha-mono mt-2 max-h-64 overflow-auto rounded-lg border border-medha-border bg-medha-muted p-3 text-[11px] text-medha-text">{JSON.stringify(proposal.plan, null, 2)}</pre>
                  </details>
                ) : null}
              </Panel>
              <Panel
                title="Decision"
                eyebrow={approvable ? "Ready — actions enabled" : "Closed — read-only"}
                description={approvable ? "Approval revalidates the exact target SHA and plan hash before any execution. Replay is idempotent." : "Only proposals in ready status can be decided. Stale or decided proposals stay inspectable."}
              >
                <label htmlFor="review-reason" className="medha-label">Reason (optional, recorded)</label>
                <textarea id="review-reason" className="field-input mt-1" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is this plan safe to execute?" disabled={!approvable} />
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button variant="primary" disabled={!approvable || busy} loading={busy} onClick={() => void act("approve")}>
                    Approve & execute
                  </Button>
                  <Button variant="secondary" disabled={!approvable || busy} onClick={() => void act("reject")}>
                    Reject
                  </Button>
                </div>
                {!approvable ? (
                  <p className="mt-2 text-[13px] text-medha-secondary">
                    {proposal.status === "stale" ? "Marked stale: the plan drifted since analysis — re-analysis is required before approval." : `Status ${proposal.status}: no decision possible.`}
                  </p>
                ) : null}
              </Panel>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}

/* ================= ORCHESTRATION ================= */

export function OrchestrationView({ projectId }: { projectId: string }) {
  const { repo, name, runs, loading, error, backendReachable, selectedId, selectRun, hydration, hydrating, refresh } =
    useProjectData(projectId);
  const selected = runs.find((r) => r.deployment_id === selectedId) ?? runs[0] ?? null;
  // O(10×N) log scan per render — memoize on the actual inputs.
  // (Hooks stay unconditional: the !repo early-return renders below them.)
  const agents = useMemo(
    () => (hydration ? resolveAgents(hydration, selected?.current_stage ?? null, selected?.status ?? null) : { agents: [], source: "logs" as const }),
    [hydration, selected?.current_stage, selected?.status],
  );
  const agentStates = agents.agents;
  const agentSource = agents.source;
  const pipeline = useMemo(
    () => (hydration ? derivePipeline(hydration.logs, selected?.current_stage ?? null, selected?.status ?? null) : []),
    [hydration, selected?.current_stage, selected?.status],
  );
  if (!repo) return <NotFound what="This project link does not decode to a known repository." />;
  const activeAgents = agentStates.filter((a) => a.state === "active" || a.state === "blocked");

  return (
    <AppShell>
      <div className="space-y-4">
        <PageHeader
          title="Orchestration"
          subtitle="Observed agent activity and pipeline progress for the selected run — derived from backend events, never simulated."
          breadcrumbs={crumbs(projectId, name, "Orchestration")}
          actions={selected ? <DemoBadge isDemo={selected.is_demo} /> : undefined}
        />
        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}
        {loading ? <LoadingGrid /> : !selected ? (
          <EmptyState title="No runs yet" body="Orchestration activity appears once this repository has a recorded run." action={<Link href="/verify" className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white">Start first run</Link>} />
        ) : (
          <>
            <RunPicker
              projectId={projectId}
              runIds={runs.map((r) => ({ id: r.deployment_id, label: `${r.deployment_id} · ${r.is_demo ? "DEMO" : "LIVE"}` }))}
              value={selected.deployment_id}
              onChange={selectRun}
              statuses={Object.fromEntries(runs.map((r) => [r.deployment_id, r.status]))}
            />
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <Panel title="Pipeline" eyebrow={selected.current_stage ? `Current: ${selected.current_stage}` : "Stages observed"}>
                <ol className="flex flex-wrap items-center gap-1.5">
                  {pipeline.map((s, i) => (
                    <li key={s.id} className="flex items-center gap-1.5">
                      {i > 0 ? <span aria-hidden className="text-medha-border-strong">→</span> : null}
                      <span className={cn(
                        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-medium",
                        s.state === "done" && "border-medha-success/30 bg-medha-success-soft text-medha-success",
                        s.state === "active" && "border-medha-run/25 bg-medha-run-soft text-medha-run-ink",
                        s.state === "blocked" && "border-medha-danger/30 bg-medha-danger-soft text-medha-danger",
                        s.state === "idle" && "border-medha-border bg-white text-medha-tertiary",
                      )}>{s.label}</span>
                    </li>
                  ))}
                </ol>
                <p className="mt-2 text-[12px] text-medha-tertiary">Stages never observed stay idle — progress is not inferred.</p>
              </Panel>
              <Panel title="Agents" eyebrow={activeAgents.length > 0 ? `${activeAgents.length} need attention` : "All observed agents settled"} description={agentSource === "backend" ? "Live backend lifecycle state (durations measured server-side)." : "Backend snapshot unavailable — states inferred from stored event keywords; unobserved stages stay idle."}>
                {hydrating ? <p className="text-[13px] text-medha-secondary">Loading events…</p> : (
                  <ul className="max-h-64 space-y-1 overflow-y-auto">
                    {agentStates.map((a) => (
                      <li key={a.id} className="rounded-lg border border-medha-border bg-white px-2.5 py-1.5 text-[13px]">
                        <p className="flex items-center gap-2 font-medium text-medha-text">
                          <span className={cn("status-dot", a.state === "done" ? "bg-medha-success" : a.state === "active" ? "bg-medha-run" : a.state === "blocked" ? "bg-medha-danger" : "bg-medha-border-strong")} aria-hidden />
                          {a.label} <span className="font-normal text-medha-tertiary">· {a.state}</span>
                        </p>
                        <p className="mt-0.5 truncate text-medha-secondary" title={a.detail}>{a.detail}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </div>
            <Panel title="Event log" eyebrow={`${hydration?.logs.length ?? 0} lines`} description="Newest last. Source, stage, and level come straight from stored backend events.">
              {!hydration || hydrating ? <p className="text-[13px] text-medha-secondary">Loading…</p> : hydration.logs.length === 0 ? (
                <p className="text-[13px] text-medha-secondary">No log lines stored for this run.</p>
              ) : (
                <details>
                  <summary className="cursor-pointer text-[13px] font-semibold text-medha-accent">Expand {hydration.logs.length} lines</summary>
                  <ol className="mt-2 max-h-80 space-y-1 overflow-y-auto">
                    {hydration.logs.map((l, i) => (
                      <li key={`${l.ts}-${i}`} className="flex items-start gap-2 rounded-lg border border-medha-border bg-white px-2.5 py-1.5 text-[12px]">
                        <span className={cn("status-dot mt-1", l.level === "error" ? "bg-medha-danger" : l.level === "warning" ? "bg-medha-warning" : "bg-medha-run")} aria-hidden />
                        <div className="min-w-0">
                          <p className="text-medha-text">{l.message}</p>
                          <p className="text-medha-tertiary">{l.source} · {l.stage ?? "—"} · {l.ts}</p>
                        </div>
                      </li>
                    ))}
                  </ol>
                </details>
              )}
            </Panel>
          </>
        )}
      </div>
    </AppShell>
  );
}

/* ================= CONSTRAINTS ================= */

export function ConstraintsView({ projectId }: { projectId: string }) {
  const { repo, name, runs, loading, error, backendReachable, selectedId, selectRun, hydration, hydrating, refresh } =
    useProjectData(projectId);
  if (!repo) return <NotFound what="This project link does not decode to a known repository." />;
  const selected = runs.find((r) => r.deployment_id === selectedId) ?? runs[0] ?? null;
  const negotiation = hydration?.negotiation ?? null;

  return (
    <AppShell>
      <div className="space-y-4">
        <PageHeader
          title="Constraint negotiation"
          subtitle="Typed constraints from specialist agents and the bounded CNP outcome (max 3 rounds). Priority order: SECURITY › RESOURCE › DEPENDENCY › PREFERENCE."
          breadcrumbs={crumbs(projectId, name, "Constraints")}
          actions={selected ? <DemoBadge isDemo={selected.is_demo} /> : undefined}
        />
        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}
        {loading ? <LoadingGrid /> : !selected ? (
          <EmptyState title="No runs yet" body="Constraints appear once a run reaches the negotiation stage." />
        ) : (
          <>
            <RunPicker
              projectId={projectId}
              runIds={runs.map((r) => ({ id: r.deployment_id, label: `${r.deployment_id} · ${r.is_demo ? "DEMO" : "LIVE"}` }))}
              value={selected.deployment_id}
              onChange={selectRun}
              statuses={Object.fromEntries(runs.map((r) => [r.deployment_id, r.status]))}
            />
            {hydrating || !hydration ? <LoadingGrid /> : (
              <>
                {negotiation ? (
                  <Panel title="Negotiation outcome" eyebrow={`Status: ${negotiation.status} · round ${negotiation.round}/${negotiation.maxRounds}`}>
                    <p className="text-[14px] font-medium text-medha-text">{negotiation.title}</p>
                    <p className="mt-1 text-[13px] text-medha-secondary">{negotiation.simpleExplanation || negotiation.conflictSummary}</p>
                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-medha-secondary">
                      {negotiation.method ? <span>Method: <span className="font-medium text-medha-text">{negotiation.method}</span></span> : null}
                      {negotiation.resolution ? <span>Resolution: <span className="font-medium text-medha-text">{negotiation.resolution}</span></span> : null}
                    </div>
                  </Panel>
                ) : (
                  <p className="rounded-xl border border-medha-border bg-white p-4 text-[13px] text-medha-secondary">No negotiation artifact for this run — it may not have reached the CNP stage.</p>
                )}
                <Panel title={`Constraints (${hydration.constraints.length})`} eyebrow="As published by specialist agents">
                  {hydration.constraints.length === 0 ? (
                    <p className="text-[13px] text-medha-secondary">No constraints recorded for this run.</p>
                  ) : (
                    <ul className="space-y-2">
                      {hydration.constraints.map((c) => (
                        <li key={c.id} className="rounded-xl border border-medha-border bg-white p-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="medha-mono text-[13px] font-semibold text-medha-text">{c.id}</span>
                            <Badge tone={c.status === "conflict" || c.status === "rejected" ? "error" : c.status === "accepted" ? "success" : "neutral"}>
                              {c.status}
                            </Badge>
                            <span className="text-[12px] text-medha-tertiary">{c.type} · {c.priority} · {c.sourceAgent}</span>
                          </div>
                          <p className="mt-1 text-[13px] text-medha-text">{c.summary}</p>
                          {c.detail ? <p className="mt-0.5 text-[12px] text-medha-secondary">{c.detail}</p> : null}
                          {c.technical ? (
                            <details className="mt-1.5">
                              <summary className="cursor-pointer text-[12px] font-semibold text-medha-accent">Technical payload</summary>
                              <pre className="medha-mono mt-1 overflow-auto rounded-lg bg-medha-muted p-2 text-[11px] text-medha-text">{JSON.stringify(c.technical, null, 2)}</pre>
                            </details>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </Panel>
              </>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}

/* ================= VERIFICATION ================= */

export function VerificationView({ projectId }: { projectId: string }) {
  const { repo, name, runs, loading, error, backendReachable, selectedId, selectRun, hydration, hydrating, refresh } =
    useProjectData(projectId);
  if (!repo) return <NotFound what="This project link does not decode to a known repository." />;
  const selected = runs.find((r) => r.deployment_id === selectedId) ?? runs[0] ?? null;
  const summary = summarizeVerification(hydration?.verification ?? null);
  const raw = hydration?.verification as {
    checks?: { id?: string; name?: string; status?: string; message?: string; rule?: string; category?: string }[];
    blocking_failures?: string[]; warnings?: string[];
  } | null;
  const critic = hydration?.critic as {
    score?: number; recommendation?: string; findings?: string[];
    breakdown?: Record<string, number>; summary?: string;
  } | null;

  return (
    <AppShell>
      <div className="space-y-4">
        <PageHeader
          title="Verification"
          subtitle="Independent verification gate plus critic review. A failed gate blocks execution — nothing proceeds silently."
          breadcrumbs={crumbs(projectId, name, "Verification")}
          actions={selected ? <DemoBadge isDemo={selected.is_demo} /> : undefined}
        />
        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}
        {loading ? <LoadingGrid /> : !selected ? (
          <EmptyState title="No runs yet" body="Verification results appear once a run reaches the verify stage." />
        ) : (
          <>
            <RunPicker
              projectId={projectId}
              runIds={runs.map((r) => ({ id: r.deployment_id, label: `${r.deployment_id} · ${r.is_demo ? "DEMO" : "LIVE"}` }))}
              value={selected.deployment_id}
              onChange={selectRun}
              statuses={Object.fromEntries(runs.map((r) => [r.deployment_id, r.status]))}
            />
            {hydrating || !hydration ? <LoadingGrid /> : !summary ? (
              <EmptyState title="No verification artifact" body="This run has no stored verification result — it likely ended before the verify stage. Pick another run above." />
            ) : (
              <>
                <Panel
                  title={summary.passed === true ? "Gate passed" : summary.passed === false ? "Gate failed" : "No conclusive result"}
                  eyebrow={`${summary.total} checks${summary.score != null ? ` · score ${summary.score}` : ""}`}
                >
                  {summary.summary ? <p className="text-[13px] text-medha-secondary">{summary.summary}</p> : null}
                  {summary.blocking.length > 0 ? (
                    <ul className="mt-2 space-y-1">
                      {summary.blocking.map((b) => (
                        <li key={b} className="flex items-start gap-2 rounded-lg border border-medha-danger/25 bg-medha-danger-soft px-2.5 py-1.5 text-[13px] text-medha-danger">
                          <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> {b}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {(raw?.warnings ?? []).length > 0 ? (
                    <ul className="mt-2 space-y-1">
                      {(raw?.warnings ?? []).map((w) => (
                        <li key={w} className="rounded-lg border border-medha-warning/30 bg-medha-warning-soft px-2.5 py-1.5 text-[13px] text-medha-warning">{w}</li>
                      ))}
                    </ul>
                  ) : null}
                  {(raw?.checks ?? []).length > 0 ? (
                    <ul className="mt-3 space-y-1.5">
                      {(raw?.checks ?? []).map((c, i) => (
                        <li key={c.id ?? i} className="flex flex-wrap items-center gap-2 rounded-lg border border-medha-border bg-white px-2.5 py-1.5 text-[13px]">
                          {checkBadge(c.status ?? "")}
                          <span className="font-medium text-medha-text">{c.name ?? c.id ?? `check ${i + 1}`}</span>
                          {c.message ? <span className="w-full text-medha-secondary">{c.message}</span> : null}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </Panel>
                <Panel title="Critic review" eyebrow={critic ? `Recommendation: ${critic.recommendation ?? "—"}` : "No critic artifact"}>
                  {!critic ? (
                    <p className="text-[13px] text-medha-secondary">No critic result stored for this run.</p>
                  ) : (
                    <>
                      <p className="flex items-center gap-1.5 text-[14px] font-semibold text-medha-text">
                        {critic.recommendation === "PASS" ? <CheckCircle2 className="h-4 w-4 text-medha-success" aria-hidden /> : null}
                        Score {critic.score ?? "—"} / 100
                      </p>
                      {critic.breakdown ? (
                        <dl className="mt-2 grid grid-cols-2 gap-1.5 text-[13px] sm:grid-cols-4">
                          {Object.entries(critic.breakdown).map(([k, v]) => (
                            <div key={k} className="rounded-lg border border-medha-border bg-white px-2.5 py-1.5">
                              <dt className="text-medha-tertiary">{k}</dt>
                              <dd className="font-semibold text-medha-text">{String(v)}</dd>
                            </div>
                          ))}
                        </dl>
                      ) : null}
                      {(critic.findings ?? []).length > 0 ? (
                        <ul className="mt-2 list-inside list-disc space-y-1 text-[13px] text-medha-secondary">
                          {(critic.findings ?? []).map((f) => <li key={f}>{f}</li>)}
                        </ul>
                      ) : null}
                      {critic.summary ? <p className="mt-2 text-[13px] text-medha-secondary">{critic.summary}</p> : null}
                    </>
                  )}
                </Panel>
                <Panel
                  title="Evidence-backed scores"
                  eyebrow="Versioned · reproducible from stored evidence"
                  description="Deployment readiness, performance, optimization, and security. Missing evidence shows as unmeasured — never as success."
                >
                  <ScoresPanel runId={selected.deployment_id} />
                </Panel>
              </>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}

/* ================= GRAPHS ================= */

export function GraphsView({ projectId }: { projectId: string }) {
  const { repo, name, runs, loading, error, backendReachable, selectedId, selectRun, hydration, hydrating, refresh } =
    useProjectData(projectId);
  if (!repo) return <NotFound what="This project link does not decode to a known repository." />;
  const selected = runs.find((r) => r.deployment_id === selectedId) ?? runs[0] ?? null;
  const nodes = hydration?.graph.nodes ?? [];
  const edges = hydration?.graph.edges ?? [];
  const rollback = hydration?.rollback ?? null;
  const impact = hydration?.changeImpact ?? null;

  return (
    <AppShell>
      <div className="space-y-4">
        <PageHeader
          title="Graphs & Impact"
          subtitle="CEG (runtime execution causality) and CIG change impact are distinct graphs — shown separately with their own evidence."
          breadcrumbs={crumbs(projectId, name, "Graphs")}
          actions={selected ? <DemoBadge isDemo={selected.is_demo} /> : undefined}
        />
        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}
        {loading ? <LoadingGrid /> : !selected ? (
          <EmptyState title="No runs yet" body="Graphs appear once a run records execution or change-impact analysis." />
        ) : (
          <>
            <RunPicker
              projectId={projectId}
              runIds={runs.map((r) => ({ id: r.deployment_id, label: `${r.deployment_id} · ${r.is_demo ? "DEMO" : "LIVE"}` }))}
              value={selected.deployment_id}
              onChange={selectRun}
              statuses={Object.fromEntries(runs.map((r) => [r.deployment_id, r.status]))}
            />
            {hydrating || !hydration ? <LoadingGrid /> : (
              <>
                <Panel
                  title="Git commit history"
                  eyebrow="Real ancestry — click a node for detail"
                  description="Actual Git parents, merges, authors, and diff summaries. CIG/CEG graphs below describe dependencies and execution, not ancestry."
                >
                  <CommitGraph projectId={projectId} />
                </Panel>
                <Panel
                  title={`Causal Execution Graph (${nodes.length} nodes, ${edges.length} edges)`}
                  eyebrow="Runtime causality — every meaningful execution action"
                  action={<Link href={`/projects/${projectId}/runs/${selected.deployment_id}`} className="text-[12px] font-semibold text-medha-accent hover:underline">Visual canvas in run detail →</Link>}
                >
                  {nodes.length === 0 ? (
                    <p className="text-[13px] text-medha-secondary">No CEG nodes recorded for this run.</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[560px] text-left text-[13px]">
                        <thead>
                          <tr className="text-[11px] uppercase tracking-wide text-medha-tertiary">
                            <th className="py-1.5 pr-3">Node</th>
                            <th className="py-1.5 pr-3">Service</th>
                            <th className="py-1.5 pr-3">Action</th>
                            <th className="py-1.5 pr-3">Status</th>
                            <th className="py-1.5">Reason</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-medha-border">
                          {nodes.map((n) => (
                            <tr key={n.id}>
                              <td className="medha-mono py-1.5 pr-3 text-medha-text">{n.id}</td>
                              <td className="py-1.5 pr-3 text-medha-text">{n.service}</td>
                              <td className="py-1.5 pr-3 text-medha-secondary">{n.action}</td>
                              <td className="py-1.5 pr-3">
                                <Badge tone={n.status === "failed" ? "error" : n.status === "rolled_back" ? "warning" : n.status === "success" || n.status === "preserved" ? "success" : "neutral"}>
                                  {String(n.status).replace(/_/g, " ")}
                                </Badge>
                              </td>
                              <td className="py-1.5 text-medha-secondary">{n.reason ?? "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {edges.length > 0 ? (
                    <details className="mt-2">
                      <summary className="cursor-pointer text-[13px] font-semibold text-medha-accent">Show {edges.length} causal edges</summary>
                      <ul className="medha-mono mt-2 space-y-0.5 text-[12px] text-medha-secondary">
                        {edges.map((e) => <li key={e.id}>{e.source} → {e.target}</li>)}
                      </ul>
                    </details>
                  ) : null}
                </Panel>

                <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                  <Panel title="Rollback scope" eyebrow={rollback ? "Dependency-aware" : "No rollback recorded"}>
                    {!rollback ? (
                      <p className="text-[13px] text-medha-secondary">
                        No rollback scope for this run — see <Link href={`/projects/${projectId}/recovery`} className="font-medium text-medha-accent hover:underline">Recovery</Link> for details when a failure occurs.
                      </p>
                    ) : (
                      <>
                        <p className="text-[13px] font-medium text-medha-text">{rollback.headline}</p>
                        <p className="mt-1 text-[13px] text-medha-secondary">{rollback.simpleExplanation}</p>
                        <p className="mt-1 text-[13px] text-medha-secondary">
                          Preserved {rollback.preserved} · rolled back {rollback.rolledBack} · failed {rollback.failed}
                        </p>
                        {rollback.details.length > 0 ? (
                          <ul className="mt-2 space-y-1">
                            {rollback.details.map((d) => (
                              <li key={d.service} className="rounded-lg border border-medha-border bg-white px-2.5 py-1.5 text-[13px]">
                                <span className="font-medium text-medha-text">{d.service}</span>
                                <span className="text-medha-tertiary"> · {String(d.status).replace(/_/g, " ")}</span>
                                {d.note ? <span className="block text-medha-secondary">{d.note}</span> : null}
                              </li>
                            ))}
                          </ul>
                        ) : null}
                      </>
                    )}
                  </Panel>
                  <Panel
                    title="Change impact"
                    eyebrow={impact ? `Risk: ${impact.risk?.level ?? "unknown"}${hydration.changeImpactIsDemo ? " · DEMO/MOCK" : ""}` : "No analysis attached"}
                  >
                    {!impact ? (
                      <p className="text-[13px] text-medha-secondary">
                        No change-impact analysis attached to this run. Run change-impact analysis against a local git revision range to populate this.
                      </p>
                    ) : (
                      <>
                        <p className="text-[13px] text-medha-text">
                          {(impact.requirements ?? []).length} verification requirements · {(impact.changed_symbols ?? []).length} changed symbols · {(impact.unresolved ?? []).length} unresolved
                        </p>
                        {(impact.requirements ?? []).slice(0, 5).map((req, i) => (
                          <p key={i} className="mt-1 text-[13px] text-medha-secondary">
                            {typeof req === "string" ? req : JSON.stringify(req)}
                          </p>
                        ))}
                        {(impact.unresolved ?? []).length > 0 ? (
                          <details className="mt-2">
                            <summary className="cursor-pointer text-[13px] font-semibold text-medha-accent">Show unresolved items</summary>
                            <pre className="medha-mono mt-1 max-h-48 overflow-auto rounded-lg bg-medha-muted p-2 text-[11px] text-medha-text">{JSON.stringify(impact.unresolved, null, 2)}</pre>
                          </details>
                        ) : null}
                      </>
                    )}
                  </Panel>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}

/* ================= RECOVERY ================= */

export function RecoveryView({ projectId }: { projectId: string }) {
  const { repo, name, runs, loading, error, backendReachable, selectedId, selectRun, hydration, hydrating, refresh } =
    useProjectData(projectId);
  if (!repo) return <NotFound what="This project link does not decode to a known repository." />;
  const selected = runs.find((r) => r.deployment_id === selectedId) ?? runs[0] ?? null;
  const rollback = hydration?.rollback ?? null;

  return (
    <AppShell>
      <div className="space-y-4">
        <PageHeader
          title="Recovery"
          subtitle="Dependency-aware scoped rollback: only causally dependent services roll back; independent successes are preserved."
          breadcrumbs={crumbs(projectId, name, "Recovery")}
          actions={selected ? <DemoBadge isDemo={selected.is_demo} /> : undefined}
        />
        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}
        {loading ? <LoadingGrid /> : !selected ? (
          <EmptyState title="No runs yet" body="Recovery scopes appear when a run fails and rolls back." />
        ) : (
          <>
            <RunPicker
              projectId={projectId}
              runIds={runs.map((r) => ({ id: r.deployment_id, label: `${r.deployment_id} · ${r.is_demo ? "DEMO" : "LIVE"}` }))}
              value={selected.deployment_id}
              onChange={selectRun}
              statuses={Object.fromEntries(runs.map((r) => [r.deployment_id, r.status]))}
            />
            {hydrating || !hydration ? <LoadingGrid /> : !rollback ? (
              <EmptyState
                title="No rollback for this run"
                body={selected.status === "failed" ? "The run failed but recorded no rollback scope." : "Only failed runs with executed services produce a rollback scope."}
                action={<Link href={`/projects/${projectId}/runs/${selected.deployment_id}`} className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white">Open run detail</Link>}
              />
            ) : (
              <Panel title={rollback.headline} eyebrow={`Preserved ${rollback.preserved} · rolled back ${rollback.rolledBack}`}>
                <p className="max-w-3xl text-[14px] leading-relaxed text-medha-secondary">{rollback.simpleExplanation}</p>
                <ul className="mt-3 space-y-1.5">
                  {rollback.details.map((d) => (
                    <li key={d.service} className={cn(
                      "rounded-xl border p-3 text-[13px]",
                      String(d.status) === "preserved" ? "border-medha-success/30 bg-medha-success-soft" : "border-medha-border bg-white",
                    )}>
                      <p className="font-semibold text-medha-text">{d.service} · {String(d.status).replace(/_/g, " ")}</p>
                      {d.note ? <p className="mt-0.5 text-medha-secondary">{d.note}</p> : null}
                    </li>
                  ))}
                </ul>
              </Panel>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}

/* ================= PROJECT RUNS ================= */

export function ProjectRuns({ projectId }: { projectId: string }) {
  const { repo, name, runs, loading, error, backendReachable, refresh } = useProjectData(projectId);
  const [filter, setFilter] = useState("all");
  if (!repo) return <NotFound what="This project link does not decode to a known repository." />;
  const visible = runs.filter((r) => {
    if (filter === "all") return true;
    if (filter === "demo") return r.is_demo;
    if (filter === "real") return !r.is_demo;
    if (filter === "failed") return r.status === "failed";
    if (filter === "running") return isRunningStatus(r.status);
    return true;
  });

  return (
    <AppShell>
      <div className="space-y-4">
        <PageHeader
          title="Runs & Executions"
          subtitle={`Every recorded execution for this repository — newest first. Statuses, durations, and outcomes come from the backend.`}
          breadcrumbs={crumbs(projectId, name, "Runs")}
          actions={<Link href="/verify" className="inline-flex items-center gap-1.5 rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white hover:bg-medha-accent-hover">New run</Link>}
        />
        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}
        <div role="group" aria-label="Run filter" className="flex flex-wrap gap-1">
          {[["all", "All"], ["running", "Running"], ["failed", "Failed"], ["demo", "Demo"], ["real", "Real"]].map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setFilter(id)}
              aria-pressed={filter === id}
              className={cn(
                "rounded-full border px-3 py-1.5 text-[13px] font-medium transition",
                filter === id ? "border-medha-text bg-medha-text text-white" : "border-medha-border bg-white text-medha-secondary hover:text-medha-text",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {loading ? <LoadingGrid /> : visible.length === 0 ? (
          <EmptyState
            title={runs.length === 0 ? "No executions recorded" : "No runs match this filter"}
            body={runs.length === 0 ? "Start the first run to begin the execution history." : "Try a different filter."}
          />
        ) : (
          <ol className="divide-y divide-medha-border overflow-hidden rounded-xl border border-medha-border bg-white">
            {visible.map((r) => (
              <li key={r.deployment_id}>
                <Link href={`/projects/${projectId}/runs/${r.deployment_id}`} className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-medha-muted/60">
                  <Badge tone={r.status === "completed" ? "success" : r.status === "failed" ? "error" : isRunningStatus(r.status) ? "info" : r.status === "partial_recovery" || r.status === "awaiting_approval" ? "warning" : "neutral"}>
                    {r.status.replace(/_/g, " ")}
                  </Badge>
                  <span className="min-w-0 flex-1">
                    <span className="medha-mono block truncate text-sm font-medium text-medha-text">{r.deployment_id}</span>
                    <span className="mt-0.5 block truncate text-xs text-medha-secondary">
                      {r.is_demo ? "DEMO" : "LIVE"} · {r.scenario ?? "real pipeline"} · {formatActivity(r.updated_at)}
                      {r.duration_seconds != null ? ` · ${r.duration_seconds}s` : ""}
                      {r.error_summary ? ` · ${r.error_summary}` : ""}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        )}
      </div>
    </AppShell>
  );
}

/* ================= PROJECT RUN DETAIL ================= */

export function ProjectRunDetail({ projectId, runId }: { projectId: string; runId: string }) {
  const { repo, name, runs, loading } = useProjectData(projectId, runId);
  if (!repo) return <NotFound what="This project link does not decode to a known repository." />;
  const belongs = runs.some((r) => r.deployment_id === runId);
  if (!loading && runs.length > 0 && !belongs) {
    return (
      <AppShell>
        <EmptyState
          title="Run not found in this project"
          body={`No run ${runId} belongs to this repository. Every artifact displayed is scoped to its project and run.`}
          action={<Link href={`/projects/${projectId}/runs`} className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white">Back to executions</Link>}
        />
      </AppShell>
    );
  }
  return <RunDetailView deploymentId={runId} />;
}

/* ================= PROJECT EVALUATIONS ================= */

interface MeasuredArtifacts {
  cnp: Record<string, unknown> | null;
  ceg: Record<string, unknown> | null;
  note: string;
}

export function ProjectEvaluations({ projectId }: { projectId: string }) {
  const { repo, name, runs, loading, error, backendReachable, refresh } = useProjectData(projectId);
  const [evalData, setEvalData] = useState<MeasuredArtifacts | null>(null);
  const [evalLoading, setEvalLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setEvalLoading(true);
    void (async () => {
      try {
        const { fetchEvaluationSummary } = await import("@/lib/api/client");
        const summary = await fetchEvaluationSummary();
        if (!cancelled) {
          setEvalData({
            cnp: (summary.cnp as Record<string, unknown> | null) ?? null,
            ceg: (summary.ceg as Record<string, unknown> | null) ?? null,
            note: summary.note ?? "",
          });
        }
      } catch {
        if (!cancelled) setEvalData(null);
      } finally {
        if (!cancelled) setEvalLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!repo) return <NotFound what="This project link does not decode to a known repository." />;
  const verified = runs.filter((r) => r.result_kind === "failed" || r.status === "completed" || r.status === "failed");

  return (
    <AppShell>
      <div className="space-y-4">
        <PageHeader
          title="Evaluations"
          subtitle="Project-level view: this repository's verification record plus the global measured CNP/CEG artifacts. Numbers come from backend runners — never hardcoded."
          breadcrumbs={crumbs(projectId, name, "Evaluations")}
        />
        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}
        {loading ? <LoadingGrid /> : (
          <>
            <Panel title="This repository's record" eyebrow={`${runs.length} runs`}>
              {runs.length === 0 ? (
                <p className="text-[13px] text-medha-secondary">No runs to summarize yet.</p>
              ) : (
                <dl className="grid grid-cols-2 gap-2 text-[13px] sm:grid-cols-4">
                  {[
                    ["Completed", String(runs.filter((r) => r.status === "completed").length)],
                    ["Failed", String(runs.filter((r) => r.status === "failed").length)],
                    ["Recovered", String(runs.filter((r) => r.status === "partial_recovery").length)],
                    ["Awaiting approval", String(runs.filter((r) => r.status === "awaiting_approval").length)],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-lg border border-medha-border bg-white px-3 py-2">
                      <dt className="text-medha-tertiary">{label}</dt>
                      <dd className="text-lg font-bold text-medha-text">{value}</dd>
                    </div>
                  ))}
                </dl>
              )}
              {verified.length > 0 ? (
                <p className="mt-2 text-[12px] text-medha-tertiary">
                  No success-rate gauges are shown — only recorded counts. Per-run evidence lives under Runs & Executions.
                </p>
              ) : null}
            </Panel>
            <Panel title="Measured CNP / CEG artifacts" eyebrow="Global runners" action={<Link href="/evaluation" className="text-[12px] font-semibold text-medha-accent hover:underline">Research eval →</Link>}>
              {evalLoading ? (
                <p className="text-[13px] text-medha-secondary">Loading measured artifacts…</p>
              ) : !evalData || (!evalData.cnp && !evalData.ceg) ? (
                <p className="text-[13px] text-medha-secondary">No evaluation artifacts generated yet. Run them from Research eval.</p>
              ) : (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div className="rounded-lg border border-medha-border bg-white p-3 text-[13px]">
                    <p className="font-semibold text-medha-text">CNP</p>
                    <pre className="medha-mono mt-1 max-h-40 overflow-auto text-[11px] text-medha-secondary">{JSON.stringify(evalData.cnp ?? null, null, 2)}</pre>
                  </div>
                  <div className="rounded-lg border border-medha-border bg-white p-3 text-[13px]">
                    <p className="font-semibold text-medha-text">CEG</p>
                    <pre className="medha-mono mt-1 max-h-40 overflow-auto text-[11px] text-medha-secondary">{JSON.stringify(evalData.ceg ?? null, null, 2)}</pre>
                  </div>
                </div>
              )}
            </Panel>
          </>
        )}
      </div>
    </AppShell>
  );
}

/* ================= PROJECT SETTINGS ================= */

export function ProjectSettings({ projectId }: { projectId: string }) {
  const router = useRouter();
  const { project, repo, name, runs, loading, error, backendReachable, latest, refresh } = useProjectData(projectId);
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [branch, setBranch] = useState<string | null>(null);
  const [deployTarget, setDeployTarget] = useState<string | null>(null);
  const [targets, setTargets] = useState<{ path: string; technologies: string[]; evidence: string[] }[] | null>(null);
  const [targetsNote, setTargetsNote] = useState<string | null>(null);
  const [saving, setSaving] = useState<"name" | "branch" | "target" | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"disconnect" | "delete" | null>(null);
  const [acting, setActing] = useState(false);
  // Load detected deployment candidates once the canonical project is known.
  useEffect(() => {
    if (!project || !projectId.startsWith("prj_")) return;
    let cancelled = false;
    void (async () => {
      try {
        const { fetchProjectTargets } = await import("@/lib/api/client");
        const t = await fetchProjectTargets(project.project_id);
        if (!cancelled) {
          setTargets(t.candidates ?? []);
          setTargetsNote(t.note ?? null);
          setDeployTarget((prev) => prev ?? t.deploy_target ?? project.deploy_target ?? null);
        }
      } catch {
        if (!cancelled) setTargets(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [project, projectId]);
  if (!repo) return <NotFound what="This project link does not decode to a known repository." />;
  const canonical = projectId.startsWith("prj_") && project != null;
  const first = runs.length > 0 ? runs[runs.length - 1] : null;

  async function save(field: "name" | "branch" | "target") {
    if (!project) return;
    if (field === "target") {
      const raw = (deployTarget ?? project.deploy_target ?? "").trim();
      setSaving(field);
      setFeedback(null);
      setActionError(null);
      try {
        const { updateProject } = await import("@/lib/api/client");
        await updateProject(project.project_id, { deploy_target: raw || "." });
        setFeedback("Deployment target updated. The next analysis uses it; prior plans are unchanged.");
        await refresh();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Could not save settings.");
      } finally {
        setSaving(null);
      }
      return;
    }
    const value = (field === "name" ? displayName ?? project.name : branch ?? project.branch).trim();
    if (!value) {
      setFeedback(field === "name" ? "Name cannot be empty." : "Branch cannot be empty.");
      return;
    }
    setSaving(field);
    setFeedback(null);
    setActionError(null);
    try {
      const { updateProject } = await import("@/lib/api/client");
      await updateProject(project.project_id, field === "name" ? { name: value } : { branch: value });
      setFeedback(field === "name" ? "Display name updated." : "Watched branch updated. Future pushes route on the new branch.");
      await refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not save settings.");
    } finally {
      setSaving(null);
    }
  }

  async function runConfirm() {
    if (!project || !confirm) return;
    setActing(true);
    setActionError(null);
    try {
      const { disconnectProject, deleteProject } = await import("@/lib/api/client");
      if (confirm === "disconnect") {
        await disconnectProject(project.project_id);
        setConfirm(null);
        await refresh();
      } else {
        await deleteProject(project.project_id);
        router.push("/projects");
      }
    } catch (err) {
      const code = err instanceof Error && "code" in err ? String((err as { code?: unknown }).code ?? "") : "";
      setActionError(
        code === "ACTIVE_RUNS"
          ? "A run is still in flight, so deletion was refused to protect it. Disconnect instead, or retry once the run finishes."
          : err instanceof Error ? err.message : "Action failed.",
      );
      setConfirm(null);
    } finally {
      setActing(false);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-2xl space-y-4">
        <PageHeader
          title="Project settings"
          subtitle="Identity and scope for this project. Changes apply to the stored connection; recorded runs are immutable."
          breadcrumbs={crumbs(projectId, name, "Settings")}
        />
        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}
        {feedback ? <p role="status" className="rounded-xl border border-medha-success/30 bg-medha-success-soft px-4 py-2.5 text-sm text-medha-success-ink">{feedback}</p> : null}
        {actionError ? <ErrorBox message={actionError} /> : null}
        {loading ? <LoadingGrid /> : (
          <>
            <Panel title="Identity" eyebrow="Stored connection">
              <dl className="space-y-1.5 text-sm">
                <div className="flex gap-2"><dt className="w-32 shrink-0 text-medha-tertiary">Display name</dt><dd className="font-medium text-medha-text">{name}</dd></div>
                <div className="flex gap-2"><dt className="w-32 shrink-0 text-medha-tertiary">Repository</dt><dd className="medha-mono break-all text-medha-text">{project ? `${project.repo_owner}/${project.repo_name}` : repo}</dd></div>
                <div className="flex gap-2"><dt className="w-32 shrink-0 text-medha-tertiary">Branch</dt><dd className="medha-mono text-medha-text">{project?.branch ?? "—"}</dd></div>
                <div className="flex gap-2"><dt className="w-32 shrink-0 text-medha-tertiary">Connection</dt><dd className="text-medha-text">{project?.connection_status ?? "legacy URL group"}</dd></div>
                <div className="flex gap-2"><dt className="w-32 shrink-0 text-medha-tertiary">Total runs</dt><dd className="text-medha-text">{runs.length}</dd></div>
                <div className="flex gap-2"><dt className="w-32 shrink-0 text-medha-tertiary">First recorded</dt><dd className="text-medha-text">{first ? formatActivity(first.created_at) : "—"}</dd></div>
                <div className="flex gap-2"><dt className="w-32 shrink-0 text-medha-tertiary">Latest run</dt><dd className="text-medha-text">{latest ? `${latest.deployment_id} · ${latest.status}` : "—"}</dd></div>
                <div className="flex gap-2"><dt className="w-32 shrink-0 text-medha-tertiary">Access</dt><dd className="text-medha-text">Owner-scoped when Clerk auth is enforced; single-operator otherwise.</dd></div>
              </dl>
            </Panel>
            {canonical && project ? (
              <Panel title="Connection" eyebrow="Rename · re-branch">
                <div className="space-y-3">
                  <div className="flex flex-wrap items-end gap-2">
                    <div className="min-w-0 flex-1">
                      <label htmlFor="ps-name" className="medha-label">Display name</label>
                      <input
                        id="ps-name" className="field-input mt-1"
                        value={displayName ?? project.name}
                        onChange={(e) => setDisplayName(e.target.value)}
                        maxLength={80}
                      />
                    </div>
                    <Button variant="secondary" loading={saving === "name"} onClick={() => void save("name")}>
                      Save name
                    </Button>
                  </div>
                  <div className="flex flex-wrap items-end gap-2">
                    <div className="min-w-0 flex-1">
                      <label htmlFor="ps-branch" className="medha-label">Watched branch</label>
                      <input
                        id="ps-branch" className="field-input mt-1"
                        value={branch ?? project.branch}
                        onChange={(e) => setBranch(e.target.value)}
                        maxLength={120}
                      />
                    </div>
                    <Button variant="secondary" loading={saving === "branch"} onClick={() => void save("branch")}>
                      Save branch
                    </Button>
                  </div>
                  <div className="flex flex-wrap items-end gap-2">
                    <div className="min-w-0 flex-1">
                      <label htmlFor="ps-target" className="medha-label">Deployment target (explicit single service)</label>
                      <input
                        id="ps-target" className="field-input mt-1"
                        value={deployTarget ?? project.deploy_target ?? ""}
                        onChange={(e) => setDeployTarget(e.target.value)}
                        maxLength={120}
                        placeholder="Auto (single app) — e.g. backend, frontend, ."
                      />
                      <p className="mt-1 text-[12px] text-medha-secondary">
                        {targets && targets.length > 0
                          ? `Detected: ${targets.map((t) => t.path).join(", ")}. V1 runs exactly one target.`
                          : (targetsNote ?? "Single-application repos need no target; multi-app repos must set one.")}
                      </p>
                    </div>
                    <Button variant="secondary" loading={saving === "target"} onClick={() => void save("target")}>
                      Save target
                    </Button>
                  </div>
                </div>
              </Panel>
            ) : (
              <Panel title="Connection" eyebrow="Legacy URL group">
                <p className="text-[13px] text-medha-secondary">
                  This view groups runs recorded before project connections existed. It is read-only:
                  connect the repository from Projects to manage it.
                </p>
              </Panel>
            )}
            <Panel title="Safety gates in force" eyebrow="Server-enforced, not UI hints">
              <ul className="list-inside list-disc space-y-1 text-sm text-medha-secondary">
                <li>Verification gate blocks execution until checks pass.</li>
                <li>Approval proposals require exact plan-hash match before execution.</li>
                <li>Docker mutates only with explicit server opt-in; otherwise the simulator runs.</li>
                <li>Rollback is dependency-aware and preserves independent successes.</li>
              </ul>
            </Panel>
            {canonical ? (
              <Panel title="Danger zone" eyebrow="Irreversible for the mapping only">
                <div className="flex flex-wrap gap-2">
                  {project?.connection_status !== "disconnected" ? (
                    <Button variant="secondary" onClick={() => setConfirm("disconnect")}>
                      Disconnect repository
                    </Button>
                  ) : null}
                  <Button variant="danger" onClick={() => setConfirm("delete")}>
                    Delete project
                  </Button>
                </div>
                <p className="mt-2 text-[13px] text-medha-secondary">
                  Disconnect stops future routing but keeps this page. Delete removes the
                  workspace entry; recorded run history stays in the backend. Deletion is
                  refused while a run is in flight.
                </p>
              </Panel>
            ) : null}
            <Panel title="Navigate" eyebrow="Project scope">
              <div className="flex flex-wrap gap-2">
                <Link href={`/projects/${projectId}/runs`} className="rounded-lg border border-medha-border bg-white px-3 py-2 text-sm font-medium text-medha-text hover:bg-medha-muted/60">Runs & Executions</Link>
                <Link href="/verify" className="rounded-lg border border-medha-border bg-white px-3 py-2 text-sm font-medium text-medha-text hover:bg-medha-muted/60">New analysis</Link>
                <Link href="/projects" className="rounded-lg border border-medha-border bg-white px-3 py-2 text-sm font-medium text-medha-text hover:bg-medha-muted/60">All projects</Link>
              </div>
            </Panel>
          </>
        )}
      </div>
      {confirm ? (
        <Dialog
          title={confirm === "disconnect" ? "Disconnect repository?" : "Delete project?"}
          danger={confirm === "delete"}
          confirmLabel={acting ? "Working…" : confirm === "disconnect" ? "Disconnect" : "Delete project"}
          confirmDisabled={acting}
          onConfirm={() => void runConfirm()}
          onCancel={() => setConfirm(null)}
          body={
            confirm === "disconnect"
              ? "Disconnect this repository? Recorded runs stay inspectable, but new pushes stop routing here."
              : "Delete this project from the workspace? Run history is preserved in the backend; the connection mapping is removed."
          }
        />
      ) : null}
    </AppShell>
  );
}

export function SectionNote({ children }: { children: ReactNode }) {
  return <p className="text-[13px] text-medha-secondary">{children}</p>;
}
