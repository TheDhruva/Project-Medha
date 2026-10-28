"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowLeft, ChevronDown } from "lucide-react";
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
import { decideProposal, type RunHealth } from "@/lib/api/client";
import {
  buildRunFeed, buildRunRoster, derivePipeline, summarizeVerification,
  useProjectData,
  type AgentState, type FeedEntry, type FeedKind, type PipelineStage,
} from "@/lib/projects/useProjectData";
import { formatDuration, runStatusBadge } from "@/lib/projects/executionPhases";
import { formatActivity, isRunningStatus, summarizeRunFailure } from "@/lib/projects/projects";
import { cn } from "@/lib/ui/cn";

/* ================= shared ================= */

function crumbs(projectId: string, name: string, tail: string) {
  return <Breadcrumbs items={[{ label: "Project Hub", href: "/projects" }, { label: name, href: `/projects/${projectId}` }, { label: tail }]} />;
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
          <option key={r.id} value={r.id}>
            {r.label}{statuses[r.id] ? ` — ${statuses[r.id]}` : ""}
          </option>
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

/* Human-readable run stamp in the user's local zone, e.g. "Oct 23, 2026 · 9:24 AM".
   Null when the run has no parseable timestamp — callers show a "Run details"
   fallback instead of inventing a date. */
function formatRunStamp(iso: string | null | undefined, opts: { year?: boolean } = {}): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const date = d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    ...(opts.year ? { year: "numeric" } : {}),
  });
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  return `${date} · ${time}`;
}

/* Plain-English run status for selectors (raw statuses stay in routing/API). */
function runStatusLabel(status: string): string {
  switch (status) {
    case "completed": return "Passed";
    case "failed": return "Failed";
    case "queued":
    case "started":
    case "running": return "Running";
    case "awaiting_approval": return "Awaiting approval";
    case "partial_recovery": return "Partial recovery";
    case "cancelled": return "Cancelled";
    default: return status.replace(/_/g, " ");
  }
}

/* Verification check status → concise label + color. Skipped/unassessed checks
   stay tertiary: they are incomplete, never passes. */
function checkStatusMeta(status: string): { label: string; className: string } {
  switch (status.toLowerCase()) {
    case "pass":
    case "passed":
      return { label: "Pass", className: "text-medha-success-ink" };
    case "fail":
    case "failed":
      return { label: "Failed", className: "text-medha-danger" };
    case "warn":
    case "warning":
      return { label: "Warning", className: "text-medha-warning" };
    case "skipped":
      return { label: "Skipped", className: "text-medha-tertiary" };
    case "pending":
      return { label: "Not run", className: "text-medha-tertiary" };
    default:
      return { label: status ? status.replace(/_/g, " ") : "Not checked", className: "text-medha-tertiary" };
  }
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
          title="Change Requests"
          subtitle="Push-triggered Approval proposals require exact plan-hash match before execution. for this repository. Approval binds to one exact plan hash — anything else fails closed as stale."
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
                    <pre className="medha-mono mt-2 max-h-64 overflow-auto rounded-lg border border-medha-border bg-medha-muted p-3 text-[12px] text-medha-text">{JSON.stringify(proposal.plan, null, 2)}</pre>
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

/* Run lifecycle state in plain English for the Activity Center header
   (runStatusLabel maps completed → "Passed" for the verification gate). */
function runLifecycleLabel(status: string): string {
  const text = status.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const RUN_TONE_TEXT: Record<string, string> = {
  completed: "text-medha-success-ink",
  failed: "text-medha-danger",
  cancelled: "text-medha-danger",
  partial_recovery: "text-medha-warning",
  awaiting_approval: "text-medha-warning",
};

/* Application health is reported only from the observed probe record —
   a completed run never implies a healthy application. */
function healthLabel(status: string): string {
  if (status === "healthy") return "Healthy";
  if (status === "unhealthy") return "Unhealthy";
  return "Not verified";
}

function healthTone(status: string): "success" | "error" | "warning" {
  if (status === "healthy") return "success";
  if (status === "unhealthy") return "error";
  return "warning";
}

function healthReason(health: RunHealth): string {
  const reason = health.reason?.trim();
  if (reason) return reason;
  if (health.health_status === "healthy") return "The last health probe reported the application healthy.";
  if (health.health_status === "unhealthy") return "The last health probe reported the application unhealthy.";
  return "Health has not been confirmed for this run.";
}

/* Restrained pastel skins for agent identity. Skin index follows the roster
   position (registry order), so an agent keeps one stable color + side for
   the life of the run — never derived from message content. */
const AGENT_SKINS = [
  { bg: "bg-medha-run-soft", ink: "text-medha-run-ink" },
  { bg: "bg-medha-success-soft", ink: "text-medha-success-ink" },
  { bg: "bg-medha-warning-soft", ink: "text-medha-warning" },
  { bg: "bg-medha-accent-soft", ink: "text-medha-accent-hover" },
  { bg: "bg-medha-muted", ink: "text-medha-secondary" },
] as const;

function agentSkin(index: number) {
  return AGENT_SKINS[index % AGENT_SKINS.length];
}

const AGENT_STATE_LABEL: Record<NonNullable<AgentState["state"]>, string> = {
  active: "Working",
  done: "Completed",
  blocked: "Failed",
  idle: "Waiting",
};

const STAGE_STATE_LABEL: Record<PipelineStage["state"], string> = {
  done: "Completed",
  active: "Running",
  blocked: "Failed",
  idle: "Waiting",
};

/* Feed badge classification → plain-English label + 10px pill styling.
   Colors reuse existing medha tokens only (var() colors take no alpha). */
const FEED_KIND_LABEL: Record<FeedKind, string> = {
  hypothesis: "Hypothesis",
  challenge: "Challenge",
  agent_activity: "Agent activity",
  verification_started: "Verification started",
  verification_check: "Verification check",
  verification_passed: "Verification passed",
  verification_failed: "Verification failed",
  coordinator_decision: "Coordinator decision",
  final_decision: "Final decision",
  merge_decision: "Merge decision",
  finding_submitted: "Finding submitted",
  note: "Note",
};

const FEED_KIND_CLASS: Record<FeedKind, string> = {
  hypothesis: "border-medha-accent bg-medha-accent-soft text-medha-accent",
  challenge: "border-medha-warning bg-medha-warning-soft text-medha-warning",
  agent_activity: "border-medha-border bg-medha-muted text-medha-tertiary",
  verification_started: "border-medha-run bg-medha-run-soft text-medha-run-ink",
  verification_check: "border-medha-border bg-white text-medha-secondary",
  verification_passed: "border-medha-success bg-medha-success-soft text-medha-success-ink",
  verification_failed: "border-medha-danger bg-medha-danger-soft text-medha-danger",
  coordinator_decision: "border-medha-accent bg-white text-medha-accent",
  final_decision: "border-medha-strong bg-medha-muted text-medha-text",
  merge_decision: "border-medha-accent bg-medha-accent-soft text-medha-accent",
  finding_submitted: "border-medha-warning bg-white text-medha-warning",
  note: "border-medha-border bg-white text-medha-tertiary",
};

function feedKindChip(kind: FeedKind) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-1.5 py-px text-[10px] font-semibold leading-none",
        FEED_KIND_CLASS[kind],
      )}
    >
      {FEED_KIND_LABEL[kind]}
    </span>
  );
}

/** Message body with an inline details toggle for long/multiline records. */
function FeedMessage({ entry }: { entry: FeedEntry }) {
  const [open, setOpen] = useState(false);
  if (!entry.longMessage) return <>{entry.message}</>;
  const firstLine = entry.message.split("\n")[0];
  const preview =
    firstLine.length > 160 || firstLine.length < entry.message.length
      ? `${firstLine.slice(0, 160)}…`
      : firstLine;
  return (
    <>
      <span className={open && entry.message.includes("\n") ? "whitespace-pre-wrap" : ""}>
        {open ? entry.message : preview}
      </span>{" "}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="rounded font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
      >
        {open ? "hide" : "details"}
      </button>
      {open && entry.technical ? (
        <span className="mt-0.5 block medha-mono text-[11px] text-medha-tertiary">
          {entry.technical}
        </span>
      ) : null}
    </>
  );
}

export function OrchestrationView({ projectId }: { projectId: string }) {
  const { repo, name, runs, loading, error, backendReachable, selectedId, selectRun, hydration, hydrating, refresh, feed: liveFeed } =
    useProjectData(projectId);
  const selected = runs.find((r) => r.deployment_id === selectedId) ?? runs[0] ?? null;
  // Feed/roster derivation is O(N) over logs — memoize on the actual inputs.
  // (Hooks stay unconditional: the !repo early-return renders below them.)
  // Live SSE feed from the hook; while it is still empty (hydration just
  // arrived, hook mocks) derive from the REST log so nothing flashes blank.
  const feed = useMemo(
    () =>
      liveFeed && liveFeed.length > 0
        ? liveFeed
        : hydration
          ? buildRunFeed(hydration.logs, hydration.agents)
          : [],
    [liveFeed, hydration],
  );
  const roster = useMemo(
    () => (hydration ? buildRunRoster(feed, hydration.agents) : []),
    [feed, hydration],
  );
  const rosterIndex = useMemo(
    () => new Map(roster.map((a, i) => [a.id, i])),
    [roster],
  );

  // Live conversation stickiness: stay pinned to the latest message only
  // while the reader is already at the bottom; otherwise count new entries
  // and offer a subtle jump affordance. Run switches reset both.
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevLenRef = useRef(0);
  const [atBottom, setAtBottom] = useState(true);
  const [newCount, setNewCount] = useState(0);
  useEffect(() => {
    const el = scrollRef.current;
    if (feed.length === prevLenRef.current) return;
    if (feed.length < prevLenRef.current || atBottom) {
      // Run switch or reader at the bottom: latest stays visible.
      prevLenRef.current = feed.length;
      setNewCount(0);
      setAtBottom(true);
      if (el) el.scrollTop = el.scrollHeight;
      return;
    }
    setNewCount((c) => c + (feed.length - prevLenRef.current));
    prevLenRef.current = feed.length;
  }, [feed, atBottom]);
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAtBottom(bottom);
    if (bottom) setNewCount(0);
  };

  if (!repo) return <NotFound what="This project link does not decode to a known repository." />;

  const runStamp = selected && !loading ? formatRunStamp(selected.updated_at) : null;
  const startStamp = selected && !loading ? formatRunStamp(selected.created_at) : null;
  const duration =
    selected?.duration_seconds != null ? formatDuration(selected.duration_seconds * 1000) : null;
  const statusLabel = selected ? runLifecycleLabel(selected.status) : null;
  const statusTone = selected ? (RUN_TONE_TEXT[selected.status] ?? "text-medha-secondary") : "text-medha-secondary";
  const running = selected ? isRunningStatus(selected.status) : false;
  const issueCount = feed.filter((entry) => entry.outcome === "error").length;
  const agentMessageCount = feed.filter((entry) => entry.isAgent).length;
  // Stale hydration from the previously selected run must never leak into
  // health/raw-event sections while the new run is loading.
  const health = !hydrating && hydration ? hydration.health : null;
  const rawLogs = !hydrating && hydration ? hydration.logs : [];
  const stages = hydration && selected
    ? derivePipeline(hydration.logs, selected.current_stage, selected.status, selected.error_code ?? null)
    : [];
  const doneStages = stages.filter((s) => s.state === "done").length;

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-[1180px] space-y-4">
        {crumbs(projectId, name, "Orchestration")}
        {/* Compact run header: when it ran, how it ended, how long — all recorded. */}
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            <h1 className="text-[26px] font-semibold leading-tight tracking-tight text-medha-text">Activity Center</h1>
            <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px]">
              {runStamp ? (
                <time dateTime={selected?.updated_at} className="text-medha-tertiary">
                  {runStamp}
                </time>
              ) : null}
              {selected && statusLabel ? (
                <span className={cn("font-medium", statusTone)}>
                  {statusLabel}
                  {duration ? <span className="font-normal text-medha-tertiary"> · {duration}</span> : null}
                </span>
              ) : null}
              {selected && !loading ? <DemoBadge isDemo={selected.is_demo} /> : null}
            </div>
          </div>
          {selected && !loading ? (
            <RunPicker
              projectId={projectId}
              runIds={runs.map((r) => ({ id: r.deployment_id, label: formatRunStamp(r.updated_at) ?? "Run" }))}
              value={selected.deployment_id}
              onChange={selectRun}
              statuses={Object.fromEntries(runs.map((r) => [r.deployment_id, runLifecycleLabel(r.status)]))}
            />
          ) : null}
        </div>
        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}
        {loading ? <LoadingGrid /> : !selected ? (
          <EmptyState title="No runs yet" body="Agent conversation appears once this repository has a recorded run." action={<Link href="/verify" className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white">Start first run</Link>} />
        ) : (
          <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
            {/* ---------- Central conversation panel ---------- */}
            <section
              aria-label="Agent conversation"
              className="medha-panel flex min-w-0 flex-col overflow-hidden"
            >
              <div className="border-b border-medha-border px-4 py-3 sm:px-5">
                <h2 className="text-[15px] font-semibold tracking-tight text-medha-text">Agent conversation</h2>
                <p className="mt-0.5 text-[12.5px] text-medha-tertiary">
                  Built from recorded backend events — agent summaries and factual system updates, never simulated dialogue.
                </p>
                {/* Participating agents discovered from this run's data. */}
                {roster.length > 0 ? (
                  <ul className="mt-2.5 flex flex-wrap gap-1.5" aria-label="Participating agents">
                    {roster.map((a, i) => {
                      const skin = agentSkin(i);
                      return (
                        <li
                          key={a.id}
                          className={cn(
                            "inline-flex items-center gap-1.5 rounded-full border border-medha-border px-2 py-0.5 text-[12px] font-medium text-medha-secondary",
                            skin.bg,
                          )}
                        >
                          <span aria-hidden className={cn("flex h-4 w-4 items-center justify-center rounded-full bg-white/70 text-[9px] font-bold", skin.ink)}>
                            {a.initials}
                          </span>
                          {a.label}
                          {a.state === "active" ? (
                            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-medha-accent" />
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
              </div>

              <div className="relative min-h-0 flex-1">
                <div
                  ref={scrollRef}
                  onScroll={handleScroll}
                  className="max-h-[min(60vh,600px)] overflow-y-auto px-3 py-3 sm:px-5"
                  tabIndex={0}
                >
                  {!hydration || hydrating ? (
                    <p className="py-6 text-center text-[13px] text-medha-secondary">Loading events…</p>
                  ) : feed.length === 0 ? (
                    <p className="py-6 text-center text-[13px] text-medha-secondary">No events are stored for this run yet.</p>
                  ) : (
                    <>
                      {issueCount > 0 ? (
                        <p className="mb-2 text-center text-[12.5px] font-semibold text-medha-danger">
                          {issueCount} {issueCount === 1 ? "error" : "errors"} recorded in this run
                        </p>
                      ) : null}
                      {agentMessageCount === 0 ? (
                        <p className="mb-2 rounded-lg bg-medha-muted px-3 py-1.5 text-center text-[12px] text-medha-secondary">
                          No agent-authored messages were recorded for this run — the timeline below is the recorded system event history.
                        </p>
                      ) : null}
                      <ol className="space-y-1" aria-label="Recorded conversation timeline">
                        {feed.map((entry, i) => {
                          const prev = feed[i - 1];
                          const grouped =
                            entry.isAgent &&
                            prev?.isAgent &&
                            prev.agentId === entry.agentId &&
                            prev.actor === entry.actor;
                          const skinIdx = entry.agentId != null ? rosterIndex.get(entry.agentId) ?? 0 : 0;
                          const skin = agentSkin(skinIdx);
                          const side = entry.isAgent && entry.agentId != null
                            ? (roster[skinIdx]?.side ?? "left")
                            : "left";

                          if (!entry.isAgent) {
                            // System lifecycle events: compact centered notices.
                            return (
                              <li
                                key={entry.key}
                                id={`feed-${i}`}
                                className="flex scroll-mt-24 justify-center py-1"
                              >
                                <p
                                  className={cn(
                                    "max-w-[92%] rounded-lg px-2.5 py-1 text-center text-[11.5px] leading-snug",
                                    entry.outcome === "error"
                                      ? "bg-medha-danger-soft text-medha-danger"
                                      : entry.outcome === "warning"
                                        ? "bg-medha-warning-soft text-medha-warning"
                                        : "bg-medha-muted text-medha-secondary",
                                  )}
                                >
                                  {feedKindChip(entry.kind)}{" "}
                                  <FeedMessage entry={entry} />
                                  {entry.timeLabel ? (
                                    <>
                                      {" "}
                                      <time dateTime={entry.ts} className="medha-mono text-[10.5px] opacity-70">
                                        {entry.timeLabel}
                                      </time>
                                    </>
                                  ) : null}
                                  {entry.outcome === "error" ? (
                                    <>
                                      {" · "}
                                      <Link
                                        href={`/projects/${projectId}/runs/${selected.deployment_id}#diagnosis`}
                                        className="font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
                                      >
                                        Open error details →
                                      </Link>
                                    </>
                                  ) : null}
                                </p>
                              </li>
                            );
                          }

                          // Agent-authored messages: aligned bubbles, sender always named.
                          return (
                            <li
                              key={entry.key}
                              id={`feed-${i}`}
                              data-agent={entry.agentId ?? "agent"}
                              data-side={side}
                              className={cn(
                                "flex scroll-mt-24 gap-2",
                                side === "right" ? "justify-end" : "justify-start",
                                grouped ? "mt-0.5" : "mt-2",
                              )}
                            >
                              {!grouped ? (
                                <span
                                  aria-hidden
                                  className={cn(
                                    "mt-5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold",
                                    skin.bg,
                                    skin.ink,
                                  )}
                                >
                                  {entry.agentId != null ? (roster[skinIdx]?.initials ?? "AG") : "AG"}
                                </span>
                              ) : null}
                              <div
                                className={cn(
                                  "max-w-[min(85%,560px)] rounded-2xl px-3 py-2",
                                  skin.bg,
                                  entry.outcome === "error" ? "ring-1 ring-inset ring-medha-danger/40" : "",
                                )}
                              >
                                <p className={cn("flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[12.5px]", skin.ink)}>
                                  <span className="font-semibold">{entry.actor}</span>
                                  {feedKindChip(entry.kind)}
                                  {entry.timeLabel ? (
                                    <time dateTime={entry.ts} className="medha-mono text-[10.5px] font-normal text-medha-tertiary">
                                      {entry.timeLabel}
                                    </time>
                                  ) : null}
                                  {entry.durationMs != null ? (
                                    <span className="text-[10.5px] font-normal text-medha-tertiary">
                                      in {formatDuration(entry.durationMs)}
                                    </span>
                                  ) : null}
                                  {entry.outcome === "error" ? (
                                    <span className="text-[10.5px] font-semibold text-medha-danger">failed</span>
                                  ) : null}
                                  {entry.outcome === "warning" ? (
                                    <span className="text-[10.5px] font-semibold text-medha-warning">warning</span>
                                  ) : null}
                                </p>
                                <p
                                  className={cn(
                                    "mt-0.5 break-words text-[13.5px] leading-relaxed",
                                    entry.outcome === "error" ? "text-medha-danger" : "text-medha-text",
                                  )}
                                >
                                  <FeedMessage entry={entry} />
                                </p>
                                {entry.error ? (
                                  <p className="mt-0.5 break-words text-[12px] text-medha-danger">{entry.error}</p>
                                ) : null}
                                {entry.handoffs.length > 0 ? (
                                  <p className="mt-1 text-[11.5px] text-medha-tertiary">
                                    ↳ Inputs from{" "}
                                    {entry.handoffs.map((h, hi) => (
                                      <span key={`${h.fromIndex}-${hi}`}>
                                        {hi > 0 ? ", " : ""}
                                        <a
                                          href={`#feed-${h.fromIndex}`}
                                          className="rounded font-medium text-medha-accent hover:underline"
                                        >
                                          {h.fromLabel}
                                        </a>
                                      </span>
                                    ))}
                                  </p>
                                ) : null}
                                {entry.outcome === "error" ? (
                                  <Link
                                    href={`/projects/${projectId}/runs/${selected.deployment_id}#diagnosis`}
                                    className="mt-1 inline-block rounded text-[12px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
                                  >
                                    Open error details →
                                  </Link>
                                ) : null}
                              </div>
                            </li>
                          );
                        })}
                      </ol>
                    </>
                  )}
                </div>
                {/* Subtle new-activity affordance: never yanks a reader of older messages. */}
                {newCount > 0 ? (
                  <button
                    type="button"
                    onClick={() => {
                      const el = scrollRef.current;
                      if (el) el.scrollTop = el.scrollHeight;
                      setAtBottom(true);
                      setNewCount(0);
                    }}
                    className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full border border-medha-accent/40 bg-white px-3 py-1 text-[12px] font-semibold text-medha-accent shadow-sm hover:bg-medha-accent-soft focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
                  >
                    ↓ {newCount} new {newCount === 1 ? "event" : "events"}
                  </button>
                ) : null}
              </div>
            </section>

            {/* ---------- Right sidebar ---------- */}
            <aside className="space-y-3" aria-label="Run details">
              {/* Run status + phases from recorded stage events. */}
              <section aria-label="Run status" className="medha-panel p-4">
                <h2 className="text-[13px] font-semibold tracking-tight text-medha-text">Run status</h2>
                {selected ? (
                  <>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px]">
                      <Badge tone={runStatusBadge(selected.status).tone}>{statusLabel}</Badge>
                      {duration ? <span className="text-medha-tertiary">{duration}</span> : null}
                    </div>
                    <dl className="mt-2 space-y-1 text-[12px]">
                      {startStamp ? (
                        <div className="flex gap-2">
                          <dt className="shrink-0 text-medha-tertiary">Start</dt>
                          <dd className="text-medha-secondary">{startStamp}</dd>
                        </div>
                      ) : null}
                      <div className="flex gap-2">
                        <dt className="shrink-0 text-medha-tertiary">Stage</dt>
                        <dd className="text-medha-secondary">{selected.current_stage ?? "Unknown"}</dd>
                      </div>
                    </dl>
                    {running && stages.length > 0 ? (
                      <div className="mt-2" aria-label="Run progress">
                        <div className="h-1.5 overflow-hidden rounded-full bg-medha-muted">
                          <div
                            className="h-full rounded-full bg-medha-accent transition-all"
                            style={{ width: `${Math.round((doneStages / stages.length) * 100)}%` }}
                          />
                        </div>
                        <p className="mt-1 text-[11px] text-medha-tertiary">
                          {doneStages} of {stages.length} stages completed
                        </p>
                      </div>
                    ) : null}
                    {stages.length > 0 ? (
                      <ul className="mt-2 space-y-1" aria-label="Pipeline phases">
                        {stages.map((s) => (
                          <li key={s.id} className="flex items-baseline justify-between gap-2 text-[12px]">
                            <span className={cn("truncate", s.state === "idle" ? "text-medha-tertiary" : "text-medha-secondary")}>
                              {s.label}
                            </span>
                            <span className="flex shrink-0 items-baseline gap-1.5">
                              <span
                                className={cn(
                                  "text-[11.5px]",
                                  s.state === "done" ? "text-medha-success-ink"
                                    : s.state === "active" ? "text-medha-accent-hover"
                                      : s.state === "blocked" ? "text-medha-danger" : "text-medha-tertiary",
                                )}
                              >
                                {s.state === "blocked" && s.reason === "config" ? "Not configured" : STAGE_STATE_LABEL[s.state]}
                              </span>
                              {s.durationMs != null ? (
                                <span className="medha-mono text-[10.5px] text-medha-tertiary">{formatDuration(s.durationMs)}</span>
                              ) : null}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-2 text-[12px] text-medha-tertiary">No stage events recorded for this run.</p>
                    )}
                  </>
                ) : null}
              </section>

              {/* Agents in this run — snapshot state only when a snapshot exists. */}
              <section aria-label="Agents in this run" className="medha-panel p-4">
                <h2 className="text-[13px] font-semibold tracking-tight text-medha-text">Agents in this run</h2>
                {roster.length === 0 ? (
                  <p className="mt-1.5 text-[12px] text-medha-tertiary">No agent activity recorded for this run.</p>
                ) : (
                  <ul className="mt-2 space-y-2" aria-label="Run agents">
                    {roster.map((a, i) => {
                      const skin = agentSkin(i);
                      return (
                        <li key={a.id} className="flex items-start gap-2">
                          <span
                            aria-hidden
                            className={cn("mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold", skin.bg, skin.ink)}
                          >
                            {a.initials}
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="flex flex-wrap items-baseline gap-x-1.5 text-[12.5px] font-semibold text-medha-text">
                              {a.label}
                              {a.state ? (
                                <span
                                  className={cn(
                                    "text-[11px] font-normal",
                                    a.state === "done" ? "text-medha-success-ink"
                                      : a.state === "active" ? "text-medha-accent-hover"
                                        : a.state === "blocked" ? "text-medha-danger" : "text-medha-tertiary",
                                  )}
                                >
                                  {AGENT_STATE_LABEL[a.state]}
                                </span>
                              ) : null}
                            </p>
                            {a.detail ? (
                              <p className="mt-0.5 break-words text-[11.5px] leading-snug text-medha-tertiary">{a.detail}</p>
                            ) : null}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>

              {/* Health comes from the observed probe only — run completion and
                  application health stay independent facts. */}
              {health ? (
                <section aria-label="Application health" className="medha-panel p-4">
                  <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                    <h2 className="text-[13px] font-semibold tracking-tight text-medha-text">Application health</h2>
                    <Badge tone={healthTone(health.health_status)}>{healthLabel(health.health_status)}</Badge>
                  </div>
                  <p className="mt-1.5 break-words text-[12px] leading-snug text-medha-secondary">{healthReason(health)}</p>
                  {health.container ? (
                    <p className="medha-mono mt-1 break-all text-[11px] text-medha-tertiary">{health.container}</p>
                  ) : null}
                  {health.checked_at ? (
                    <p className="mt-1 text-[11px] text-medha-tertiary">
                      Checked {formatRunStamp(health.checked_at)}
                    </p>
                  ) : null}
                  <Link
                    href={`/projects/${projectId}#deployment-health`}
                    className="mt-1.5 inline-block rounded text-[12px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
                  >
                    Health details →
                  </Link>
                </section>
              ) : null}

              {/* Raw stored events stay available but out of the way by default. */}
              {rawLogs.length > 0 ? (
                <details id="technical-details" className="medha-panel p-4">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent [&::-webkit-details-marker]:hidden">
                    <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                      <span className="text-[13px] font-semibold tracking-tight text-medha-text">
                        Technical details
                      </span>
                      <span className="text-[11.5px] text-medha-secondary">{rawLogs.length} raw events</span>
                    </span>
                    <ChevronDown className="h-4 w-4 shrink-0 text-medha-tertiary transition-transform" aria-hidden />
                  </summary>
                  <ol className="mt-3 max-h-72 space-y-1 overflow-y-auto">
                    {rawLogs.map((l, i) => (
                      <li
                        key={`${l.ts}-${i}`}
                        className="medha-mono flex flex-wrap gap-x-2 text-[11.5px] leading-5 text-medha-tertiary"
                      >
                        <span className="shrink-0">{l.ts}</span>
                        <span
                          className={cn(
                            "shrink-0 font-semibold",
                            l.level === "error" ? "text-medha-danger" : l.level === "warning" ? "text-medha-warning" : "",
                          )}
                        >
                          {l.level}
                        </span>
                        <span className="shrink-0">{l.type}</span>
                        <span className="shrink-0">{l.source}</span>
                        {l.status ? <span className="shrink-0">{l.status}</span> : null}
                        {l.is_demo ? <span className="shrink-0">demo</span> : null}
                        <span className="min-w-0 flex-1 break-words text-medha-secondary">{l.message}</span>
                      </li>
                    ))}
                  </ol>
                </details>
              ) : null}
            </aside>
          </div>
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
          title="Conflict Resolution"
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
                              <pre className="medha-mono mt-1 overflow-auto rounded-lg bg-medha-muted p-2 text-[12px] text-medha-text">{JSON.stringify(c.technical, null, 2)}</pre>
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
  const { repo, runs, loading, error, backendReachable, selectedId, selectRun, hydration, hydrating, refresh } =
    useProjectData(projectId);
  const searchParams = useSearchParams();
  const runParam = searchParams.get("run");
  useEffect(() => {
    if (runParam && runs.some((r) => r.deployment_id === runParam)) selectRun(runParam);
  }, [runParam, runs, selectRun]);
  if (!repo) return <NotFound what="This project link does not decode to a known repository." />;
  const selected = runs.find((r) => r.deployment_id === selectedId) ?? runs[0] ?? null;
  const summary = summarizeVerification(hydration?.verification ?? null);
  // Normalized coverage strip; null when the backend recorded none (older runs).
  const coverage = hydration?.coverage ?? null;
  const raw = hydration?.verification as {
    checks?: {
      id?: string; name?: string; status?: string; message?: string;
      rule?: string; category?: string; evidence?: unknown;
    }[];
    blocking_failures?: string[]; warnings?: string[];
  } | null;
  const critic = hydration?.critic as {
    score?: number; recommendation?: string; findings?: string[];
    breakdown?: Record<string, number>; summary?: string;
  } | null;

  const runStamp = selected && !loading ? formatRunStamp(selected.updated_at, { year: true }) : null;
  const criticMeta = (() => {
    if (!critic) return null;
    switch (critic.recommendation) {
      case "PASS": return { label: "Recommended", tone: "success" as const };
      case "WARN": return { label: "Review advised", tone: "warning" as const };
      case "BLOCK": return { label: "Do not proceed", tone: "error" as const };
      default: return { label: critic.recommendation ?? "—", tone: "neutral" as const };
    }
  })();
  const BREAKDOWN_TEXT: Record<string, string> = {
    security: "Security",
    completeness: "Completeness",
    constraints: "Constraint handling",
    intentAlignment: "Matches the request",
  };

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-[1120px] space-y-4">
        {/* Compact header: what happened, when, and the one gate result. */}
        <div>
          <h1 className="text-[26px] font-semibold leading-tight tracking-tight text-medha-text">Verification</h1>
          <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1">
            {loading ? null : runStamp ? (
              <time dateTime={selected?.updated_at} className="text-[13px] text-medha-tertiary">
                {runStamp}
              </time>
            ) : (
              <span className="text-[13px] text-medha-tertiary">Run details</span>
            )}
            {summary?.passed === true ? <Badge tone="success">Passed</Badge> : null}
            {summary?.passed === false ? <Badge tone="error">Failed</Badge> : null}
            {selected?.is_demo ? (
              <span className="text-[12px] font-semibold text-medha-tertiary">DEMO/MOCK</span>
            ) : null}
          </div>
        </div>
        {!backendReachable && !loading ? <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => refresh()} /> : null}
        {loading ? <LoadingGrid /> : !selected ? (
          <EmptyState title="No runs yet" body="Verification results appear once a run reaches the verify stage." />
        ) : (
          <>
            <RunPicker
              projectId={projectId}
              runIds={runs.map((r) => ({
                id: r.deployment_id,
                label: formatRunStamp(r.updated_at) ?? "Run details",
              }))}
              value={selected.deployment_id}
              onChange={selectRun}
              statuses={Object.fromEntries(runs.map((r) => [r.deployment_id, runStatusLabel(r.status)]))}
            />
            {hydrating || !hydration ? <LoadingGrid /> : (
              <>
                <ScoresPanel projectId={projectId} runId={selected.deployment_id} />

                {/* Coverage strip: how much of the gate was actually assessed.
                    Absent coverage is stated as unavailable, never as passed. */}
                <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border border-medha-border bg-white px-3.5 py-2.5 text-[13px]">
                  <span className="font-semibold text-medha-text">Coverage</span>
                  {coverage ? (
                    <>
                      <span className="text-medha-secondary">
                        checks assessed {coverage.counts.assessed}/{coverage.counts.applicable} (
                        {Math.round(coverage.counts.ratio * 100)}%)
                      </span>
                      <span className="text-medha-tertiary">
                        {coverage.counts.passed} passed · {coverage.counts.failed} failed ·{" "}
                        {coverage.counts.warnings} warnings · {coverage.counts.skipped} skipped ·{" "}
                        {coverage.counts.not_assessed} not assessed
                        {coverage.counts.not_applicable > 0
                          ? ` · ${coverage.counts.not_applicable} not applicable`
                          : ""}
                      </span>
                      {coverage.reason ? (
                        <span className="min-w-0 text-medha-tertiary">{coverage.reason}</span>
                      ) : null}
                    </>
                  ) : (
                    <span className="text-medha-secondary">coverage unavailable for this run</span>
                  )}
                </div>

                {/* Every check stays accessible behind one control; the summary
                    row keeps the real result (including failures) visible. */}
                <details id="checks" className="medha-panel p-4 sm:p-5">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent [&::-webkit-details-marker]:hidden">
                    <span className="flex min-w-0 flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
                      <span className="text-[17px] font-semibold leading-snug tracking-tight text-medha-text">
                        Verification checks
                      </span>
                      {summary ? (
                        <span className="text-[13px] text-medha-secondary">
                          {summary.passedCount}/{summary.assessed} passed (assessed checks only)
                          {summary.failed > 0 ? (
                            <span className="text-medha-danger"> · {summary.failed} failed</span>
                          ) : null}
                          {summary.warnings > 0 ? (
                            <span className="text-medha-warning"> · {summary.warnings} to review</span>
                          ) : null}
                          {summary.pending > 0 ? (
                            <span className="text-medha-tertiary"> · {summary.pending} not run</span>
                          ) : null}
                        </span>
                      ) : (
                        <span className="text-[13px] text-medha-secondary">No result stored</span>
                      )}
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      <Link href={`/projects/${projectId}/runs/${selected.deployment_id}`} onClick={(e) => e.stopPropagation()} className="rounded text-[13px] font-semibold text-medha-accent hover:underline">
                        Run details →
                      </Link>
                      <ChevronDown className="h-4 w-4 shrink-0 text-medha-tertiary transition-transform" aria-hidden />
                    </span>
                  </summary>
                  <div className="mt-4">
                    {summary?.blocking.length ? (
                      <ul className="space-y-1">
                        {summary.blocking.map((b) => (
                          <li key={b} className="rounded-lg border border-medha-danger/25 bg-medha-danger-soft px-2.5 py-1.5 text-[13px] text-medha-danger">
                            {b}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {(raw?.warnings ?? []).length > 0 ? (
                      <ul className={cn("space-y-1", summary?.blocking.length ? "mt-2.5" : "")}>
                        {(raw?.warnings ?? []).map((w) => (
                          <li key={w} className="rounded-lg border border-medha-warning/30 bg-medha-warning-soft px-2.5 py-1.5 text-[13px] text-medha-warning">{w}</li>
                        ))}
                      </ul>
                    ) : null}
                    {coverage ? (
                      coverage.normalized.length > 0 ? (
                        <ul className={cn("divide-y divide-medha-border border-t border-medha-border", summary?.blocking.length || (raw?.warnings ?? []).length ? "mt-3" : "")}>
                          {coverage.normalized.map((check) => {
                            const matched = (raw?.checks ?? []).find(
                              (c) => c.id === check.id || c.name === check.title,
                            );
                            const notRun = check.status === "not_assessed";
                            const label = notRun
                              ? check.required
                                ? "required — did not run"
                                : "did not run"
                              : check.status === "skipped"
                                ? "skipped / not applicable"
                                : check.status === "passed"
                                  ? "passed"
                                  : check.status === "failed"
                                    ? "failed"
                                    : "warning";
                            const toneClass =
                              check.status === "passed"
                                ? "text-medha-success-ink"
                                : check.status === "failed"
                                  ? "text-medha-danger"
                                  : check.status === "warning"
                                    ? "text-medha-warning"
                                    : notRun && check.required
                                      ? "text-medha-warning"
                                      : "text-medha-tertiary";
                            const detail = matched?.message ?? (check.finding || null);
                            const evidence = matched?.evidence;
                            return (
                              <li key={check.id} className="py-2">
                                <details>
                                  <summary className="flex cursor-pointer list-none items-center gap-3 rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent [&::-webkit-details-marker]:hidden">
                                    <span className={cn("w-44 shrink-0 text-[12.5px] font-semibold", toneClass)}>
                                      {label}
                                    </span>
                                    <span className="min-w-0 flex-1 text-[13.5px] font-medium text-medha-text">
                                      {check.title}
                                    </span>
                                    {check.required ? (
                                      <span className="shrink-0 text-[11.5px] text-medha-tertiary">required</span>
                                    ) : null}
                                  </summary>
                                  {detail || evidence != null ? (
                                    <div className="mt-0.5 space-y-0.5 pl-[11.5rem] text-[12.5px]">
                                      {detail ? <p className="text-medha-secondary">{detail}</p> : null}
                                      {evidence != null ? (
                                        <p className="medha-mono break-words text-[11.5px] text-medha-tertiary">
                                          {typeof evidence === "string" ? evidence : JSON.stringify(evidence)}
                                        </p>
                                      ) : null}
                                    </div>
                                  ) : null}
                                </details>
                              </li>
                            );
                          })}
                        </ul>
                      ) : (
                        <p className="text-[13px] text-medha-tertiary">No individual checks were recorded.</p>
                      )
                    ) : (raw?.checks ?? []).length > 0 ? (
                      <ul className={cn("divide-y divide-medha-border border-t border-medha-border", summary?.blocking.length || (raw?.warnings ?? []).length ? "mt-3" : "")}>
                        {(raw?.checks ?? []).map((c, i) => {
                          const meta = checkStatusMeta(c.status ?? "");
                          return (
                            <li key={c.id ?? i} className="flex flex-col gap-0.5 py-2">
                              <div className="flex min-w-0 items-center gap-3">
                                <span className={cn("w-20 shrink-0 text-[12.5px] font-semibold", meta.className)}>
                                  {meta.label}
                                </span>
                                <span className="min-w-0 flex-1 text-[13.5px] font-medium text-medha-text">
                                  {c.name ?? c.id ?? `check ${i + 1}`}
                                </span>
                              </div>
                              {c.message ? (
                                <p className="min-w-0 pl-[5.75rem] text-[12.5px] leading-4 text-medha-secondary">{c.message}</p>
                              ) : null}
                            </li>
                          );
                        })}
                      </ul>
                    ) : summary ? (
                      <p className="text-[13px] text-medha-tertiary">No individual checks were recorded.</p>
                    ) : (
                      <p className="text-[13.5px] text-medha-secondary">
                        No verification result was stored for this run. It likely ended before the verify stage.
                      </p>
                    )}
                    {(raw?.checks ?? []).some((c) => c.rule || c.category) ? (
                      <details className="mt-3">
                        <summary className="cursor-pointer rounded text-[13px] font-semibold text-medha-accent transition-colors hover:text-medha-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">
                          Technical details
                        </summary>
                        <ul className="mt-2 space-y-1 text-[12.5px] text-medha-tertiary">
                          {(raw?.checks ?? []).map((c, i) => (
                            <li key={c.id ?? i} className="medha-mono">
                              {c.id ?? c.name ?? `check ${i + 1}`}
                              {c.rule ? ` · rule: ${c.rule}` : ""}
                              {c.category ? ` · category: ${c.category}` : ""}
                            </li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                  </div>
                </details>

                {critic && criticMeta ? (
                  <Panel title="AI review">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <Badge tone={criticMeta.tone}>{criticMeta.label}</Badge>
                      <span className="text-[14px] font-semibold text-medha-text">
                        AI score {critic.score ?? "—"}
                        {typeof critic.score === "number" ? "/100" : ""}
                      </span>
                    </div>
                    {(critic.findings ?? []).length > 0 ? (
                      <ul className="mt-2 space-y-1">
                        {(critic.findings ?? []).slice(0, 4).map((f) => (
                          <li key={f} className="flex gap-1.5 text-[13px] leading-5 text-medha-secondary">
                            <span aria-hidden className="text-medha-border-strong">·</span>
                            <span className="min-w-0">{f}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-2 text-[13px] text-medha-tertiary">No findings recorded.</p>
                    )}
                    {critic.breakdown || critic.summary ? (
                      <details className="mt-2.5">
                        <summary className="cursor-pointer rounded text-[13px] font-semibold text-medha-accent transition-colors hover:text-medha-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">
                          More about this review
                        </summary>
                        {critic.breakdown ? (
                          <dl className="mt-2 grid grid-cols-2 gap-1.5 text-[13px] sm:grid-cols-4">
                            {Object.entries(critic.breakdown).map(([k, v]) => (
                              <div key={k} className="rounded-lg border border-medha-border bg-white px-2.5 py-1.5">
                                <dt className="text-medha-tertiary">{BREAKDOWN_TEXT[k] ?? k}</dt>
                                <dd className="font-semibold text-medha-text">{v}</dd>
                              </div>
                            ))}
                          </dl>
                        ) : null}
                        {critic.summary ? (
                          <p className="mt-2 text-[13px] text-medha-secondary">{critic.summary}</p>
                        ) : null}
                      </details>
                    ) : null}
                  </Panel>
                ) : null}
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
          title="Architecture Explorer"
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
                          <tr className="text-[12px] font-semibold text-medha-secondary">
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
                            <pre className="medha-mono mt-1 max-h-48 overflow-auto rounded-lg bg-medha-muted p-2 text-[12px] text-medha-text">{JSON.stringify(impact.unresolved, null, 2)}</pre>
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
          title="Run History"
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
                    <span className="medha-mono block truncate text-[14px] font-semibold text-medha-text">{r.deployment_id}</span>
                    <span className="mt-0.5 block text-[12.5px] leading-4 text-medha-secondary">
                      {r.is_demo ? "DEMO" : "LIVE"} · {r.scenario ?? "real pipeline"} · {formatActivity(r.updated_at)}
                      {r.duration_seconds != null ? ` · ${r.duration_seconds}s` : ""}
                    </span>
                    {r.status === "failed" ? (
                      <span className="mt-1 block break-words text-[12.5px] leading-4 text-medha-text">
                        <span className="font-semibold text-medha-danger">Failure: </span>
                        {summarizeRunFailure(r)}
                      </span>
                    ) : null}
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
  return <RunDetailView deploymentId={runId} projectId={projectId} />;
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
          title="Evaluation Results"
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
                <p className="text-[13px] text-medha-secondary">No evaluation artifacts generated yet. Run them from Research Results.</p>
              ) : (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div className="rounded-lg border border-medha-border bg-white p-3 text-[13px]">
                    <p className="font-semibold text-medha-text">CNP</p>
                    <pre className="medha-mono mt-1 max-h-40 overflow-auto text-[12px] text-medha-secondary">{JSON.stringify(evalData.cnp ?? null, null, 2)}</pre>
                  </div>
                  <div className="rounded-lg border border-medha-border bg-white p-3 text-[13px]">
                    <p className="font-semibold text-medha-text">CEG</p>
                    <pre className="medha-mono mt-1 max-h-40 overflow-auto text-[12px] text-medha-secondary">{JSON.stringify(evalData.ceg ?? null, null, 2)}</pre>
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
        // Empty clears the stored target (back to auto-resolution); "."
        // names the repository root when it is a detected application.
        await updateProject(project.project_id, { deploy_target: raw });
        setDeployTarget(raw || null);
        setFeedback(
          raw
            ? "Deployment target updated. The next analysis uses it; prior plans are unchanged."
            : "Deployment target cleared. The next analysis auto-resolves a single application or asks for a target.",
        );
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
                      {targets && targets.length > 1 ? (
                        <div className="mt-1.5 flex flex-wrap gap-1.5" aria-label="Detected applications">
                          {targets.map((t) => (
                            <button
                              key={t.path}
                              type="button"
                              onClick={() => setDeployTarget(t.path)}
                              title={(t.technologies ?? []).join(", ") || t.path}
                              className="rounded-md border border-medha-border bg-white px-2 py-1 font-mono text-[12.5px] text-medha-text hover:bg-medha-muted/60"
                            >
                              {t.path}
                            </button>
                          ))}
                          <button
                            type="button"
                            onClick={() => setDeployTarget("")}
                            title="Clear the stored target (back to auto-resolution)"
                            className="rounded-md border border-medha-border bg-white px-2 py-1 text-[12.5px] text-medha-secondary hover:bg-medha-muted/60"
                          >
                            Clear
                          </button>
                        </div>
                      ) : null}
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
                <Link href="/verify" className="rounded-lg border border-medha-border bg-white px-3 py-2 text-sm font-medium text-medha-text hover:bg-medha-muted/60">New run</Link>
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
