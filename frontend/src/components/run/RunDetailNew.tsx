"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { ArrowLeft, CheckCircle2, XCircle, AlertTriangle, Loader2, Copy, Check, PlayCircle, GitCommitHorizontal } from "lucide-react";
import { ConstraintNegotiation } from "@/components/constraints/ConstraintNegotiation";
// Heavy views load on demand: graph lib is not needed for the initial paint.
const ChangeImpactPanel = dynamic(
  () => import("@/components/changeintel/ChangeImpactPanel").then((m) => m.ChangeImpactPanel),
  { ssr: false, loading: () => null },
);
const CausalExecutionGraph = dynamic(
  () => import("@/components/graph/CausalExecutionGraph").then((m) => m.CausalExecutionGraph),
  { ssr: false, loading: () => null },
);
import { AgentActivity } from "@/components/agents/AgentActivity";
import { Pipeline } from "@/components/pipeline/Pipeline";
import { VerificationPanel } from "@/components/verification/VerificationPanel";
const LiveSystemTrace = dynamic(
  () => import("@/components/trace/LiveSystemTrace").then((m) => m.LiveSystemTrace),
  { ssr: false, loading: () => null },
);
import { WhatMedhaIsDoing } from "@/components/explainability/WhatMedhaIsDoing";
import { ViewModeToggle } from "@/components/explainability/ViewModeToggle";
import { AppShell } from "@/components/layout/AppShell";
import { MedhaFace, faceStateFromRun } from "@/components/medha/MedhaFace";
import { DeploymentProvider, useDeployment } from "@/context/DeploymentContext";
import type { DeploymentSnapshot } from "@/lib/demo/types";
import {
  DecisionCard,
  SummaryRow,
  SectionShell,
  buildRemediation,
  formatDuration,
  modeLabel,
} from "@/components/run-detail/Cards";
import { EnvBadge, ExecutionModeBadge } from "@/components/ui/Section";
import { RuntimeLogsPanel } from "@/components/run-detail/RuntimeLogs";
import { TargetSelectionCard } from "@/components/run/TargetSelectionCard";
import {
  createProjectRun,
  fetchCommitDetail,
  fetchCommitHistory,
  fetchDeployment,
  fetchProject,
  type CommitDetail,
  type HistoryCommit,
  type Project,
} from "@/lib/api/client";
import { formatActivity } from "@/lib/projects/projects";
import { labelStatus, statusGlyph } from "@/lib/ui/status";
import { cn } from "@/lib/ui/cn";

function runTitle(snapshot: DeploymentSnapshot, deploymentId: string): string {
  if (snapshot.changeIntel?.label) return snapshot.changeIntel.label;
  if (snapshot.deploymentId) return `Run ${snapshot.deploymentId}`;
  return "Verification run";
}

function StatusLine({ snapshot }: { snapshot: DeploymentSnapshot }) {
  const s = snapshot.runStatus;
  if (s === "succeeded")
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-medha-success">
        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> Completed
      </span>
    );
  if (s === "partial_recovery")
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-medha-warning">
        <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> Recovered
      </span>
    );
  if (s === "failed")
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-medha-danger">
        <XCircle className="h-3.5 w-3.5" aria-hidden /> Blocked
      </span>
    );
  if (s === "running")
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-medha-run">
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> Running
      </span>
    );
  return <span className="text-xs text-medha-tertiary">Not started</span>;
}

/* ------------------------- diagnosis helpers ------------------------- */

function concise(message: string, limit = 240): string {
  const oneLine = message.replace(/\s+/g, " ").trim();
  return oneLine.length > limit ? `${oneLine.slice(0, limit)}…` : oneLine;
}

/** Split a backend failure message into a confirmed cause vs hypotheses. */
function splitCause(message: string): { fact: string; hypothesis: string | null } {
  const match = /likely[^.]*\./i.exec(message);
  if (!match) return { fact: message.trim(), hypothesis: null };
  return {
    fact: message.slice(0, match.index).replace(/\s+/g, " ").trim(),
    hypothesis: match[0].replace(/\s+/g, " ").trim(),
  };
}

function probeInfo(message: string): { url: string | null; mapping: string | null } {
  const url = /probing\s+(https?:\/\/[^\s)]+)/i.exec(message)?.[1] ?? null;
  const mapping =
    /published\s+host\s+([^\s]+)\s+→\s+container:([^\s)]+)/i.exec(message) != null
      ? ((): string => {
          const m = /published\s+host\s+([^\s]+)\s+→\s+container:([^\s)]+)/i.exec(message)!;
          return `host ${m[1]} → container:${m[2]}`;
        })()
      : /published\s+([^.)]+)\)/i.exec(message)?.[1]?.trim() ?? null;
  return { url, mapping };
}

function logTail(text: string | undefined, lines = 8): string {
  if (!text) return "";
  return text.trim().split("\n").slice(-lines).join("\n");
}

function shortSha(rev: string | null | undefined): string | null {
  if (!rev) return null;
  return rev.length > 12 ? rev.slice(0, 7) : rev;
}

/* ------------------------------ diagnosis ------------------------------ */

function DiagnosisCard({ snapshot }: { snapshot: DeploymentSnapshot }) {
  const failed = snapshot.runStatus === "failed" || snapshot.runStatus === "partial_recovery";
  const running = snapshot.runStatus === "running";
  const message = snapshot.result?.message ?? snapshot.explain.technicalText ?? "";
  const { fact, hypothesis } = useMemo(() => splitCause(message), [message]);
  const probe = useMemo(() => probeInfo(message), [message]);
  const [copied, setCopied] = useState(false);

  const stderrTail = logTail(snapshot.runtimeLogs?.stderr);
  const stdoutTail = logTail(snapshot.runtimeLogs?.stdout);
  const appLog = stderrTail || stdoutTail;
  const revision =
    shortSha(snapshot.changeIntel?.changeset.target_sha) ??
    shortSha(snapshot.changeIntel?.changeset.target_revision);
  const build = snapshot.result?.build ?? null;
  const remediation = buildRemediation(build?.error_code);

  const copyLogs = async () => {
    if (!appLog) return;
    try {
      await navigator.clipboard.writeText(appLog);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable — selection still works */
    }
  };

  return (
    <section id="diagnosis" aria-label={failed ? "Failure diagnosis" : "Run outcome"} className="scroll-mt-20 rounded-xl border border-medha-border bg-white p-4 sm:p-5">
      <p className="medha-label">
        {failed ? "Diagnosis" : running ? "Current state" : "Outcome"}
      </p>
      {failed ? (
        <div className="mt-2 space-y-2.5">
          <div>
            <p className="text-[12px] font-semibold uppercase tracking-wide text-medha-danger">Failure</p>
            <p className="mt-0.5 text-[13.5px] leading-relaxed text-medha-text">{concise(fact, 320)}</p>
            {hypothesis ? (
              <p className="mt-1 text-[13.5px] italic leading-relaxed text-medha-secondary">
                Hypothesis (unverified): {hypothesis}
              </p>
            ) : null}
          </div>
          {build ? (
            <div>
              <p className="medha-label">
                Build failure{build.stage ? ` (${build.stage})` : ""}
              </p>
              <dl className="mt-1 grid gap-x-4 gap-y-1 text-[13px] text-medha-secondary sm:grid-cols-2">
                {build.command ? (
                  <div className="sm:col-span-2">
                    <dt className="inline font-semibold text-medha-text">Command: </dt>
                    <dd className="medha-mono inline break-all">{build.command}</dd>
                  </div>
                ) : null}
                {build.package_manager ? (
                  <div><dt className="inline font-semibold text-medha-text">Package manager: </dt><dd className="inline">{build.package_manager}</dd></div>
                ) : null}
                {build.exit_code != null ? (
                  <div><dt className="inline font-semibold text-medha-text">Exit code: </dt><dd className="medha-mono inline">{build.exit_code}</dd></div>
                ) : null}
                {build.error_code ? (
                  <div><dt className="inline font-semibold text-medha-text">Error code: </dt><dd className="medha-mono inline">{build.error_code}</dd></div>
                ) : null}
                {build.app_root ? (
                  <div><dt className="inline font-semibold text-medha-text">Application root: </dt><dd className="medha-mono inline">{build.app_root}</dd></div>
                ) : null}
              </dl>
              {remediation ? (
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-medha-text">
                  <span className="font-semibold">Suggested fix: </span>{remediation}
                </p>
              ) : null}
              {build.log ? (
                <details className="mt-1.5">
                  <summary className="cursor-pointer text-[13.5px] font-semibold text-medha-accent">
                    Build output {build.log_truncated ? "(truncated to the last 8000 characters)" : "(complete, bounded)"}
                  </summary>
                  <pre className="medha-mono mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-medha-border bg-medha-muted p-2.5 text-[12px] leading-relaxed text-medha-text">
                    {build.log}
                  </pre>
                </details>
              ) : null}
            </div>
          ) : null}
          <div className="grid gap-2.5 sm:grid-cols-2">
            <div>
              <p className="medha-label">Readiness probe</p>
              <p className="medha-mono mt-0.5 break-all text-[13px] text-medha-text">{probe.url ?? "No readiness probe was attempted (execution did not reach it)."}</p>
              {probe.mapping ? <p className="mt-0.5 text-[13px] text-medha-secondary">Published {probe.mapping}</p> : null}
            </div>
            <div>
              <p className="medha-label">Execution</p>
              <p className="mt-0.5 text-[13px] text-medha-secondary">
                Stage {snapshot.explain.currentStage ?? snapshot.runStatus}
                {snapshot.durationSeconds != null ? ` · ${formatDuration(snapshot.durationSeconds)}` : ""}
                {modeLabel(snapshot.executionMode) ? ` · ${modeLabel(snapshot.executionMode)}` : ""}
                {revision ? ` · rev ${revision}` : ""}
              </p>
            </div>
          </div>
          {appLog ? (
            <div>
              <div className="flex items-center justify-between gap-2">
                <p className="medha-label">
                  Application logs {stderrTail ? "(stderr)" : "(stdout)"} — tail
                </p>
                <button
                  type="button"
                  onClick={() => void copyLogs()}
                  className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[12px] font-medium text-medha-secondary hover:bg-medha-muted hover:text-medha-text"
                >
                  {copied ? <Check className="h-3 w-3" aria-hidden /> : <Copy className="h-3 w-3" aria-hidden />}
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <pre className="medha-mono mt-1 max-h-36 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-medha-border bg-medha-muted p-2.5 text-[12px] leading-relaxed text-medha-text">
                {appLog}
              </pre>
            </div>
          ) : null}
          {message.length > 340 ? (
            <details>
              <summary className="cursor-pointer text-[13.5px] font-semibold text-medha-accent">
                Full diagnostic evidence
              </summary>
              <p className="mt-1 whitespace-pre-wrap break-words text-[13px] leading-relaxed text-medha-secondary">
                {message}
              </p>
            </details>
          ) : null}
        </div>
      ) : (
        <div className="mt-1.5 space-y-1.5">
          <p className="text-[13.5px] leading-relaxed text-medha-text">
            {running ? snapshot.explain.simpleText : message || snapshot.explain.simpleText}
          </p>
          {!running && snapshot.runStatus === "succeeded" ? (
            <p className="text-[13px] text-medha-tertiary">
              Completed execution is not a health claim — application health is reported separately on the project overview.
            </p>
          ) : null}
          <p className="text-[13px] text-medha-secondary">
            Stage {snapshot.explain.currentStage ?? snapshot.runStatus}
            {snapshot.durationSeconds != null ? ` · ${formatDuration(snapshot.durationSeconds)}` : ""}
            {modeLabel(snapshot.executionMode) ? ` · ${modeLabel(snapshot.executionMode)}` : ""}
            {revision ? ` · rev ${revision}` : ""}
          </p>
        </div>
      )}
    </section>
  );
}

/* ------------------------------ CEG preview ------------------------------ */

const NODE_SEVERITY: Record<string, number> = {
  failed: 0,
  rolled_back: 1,
  running: 2,
  pending: 3,
  success: 4,
  preserved: 5,
};

function CegPreview({ snapshot, graphsHref }: { snapshot: DeploymentSnapshot; graphsHref: string | null }) {
  const [expanded, setExpanded] = useState(false);
  const nodes = snapshot.graph.nodes;
  const edges = snapshot.graph.edges;
  const rollback = snapshot.rollback;

  const services = useMemo(() => {
    const byService = new Map<string, { status: string; count: number }>();
    for (const n of nodes) {
      const prev = byService.get(n.service);
      const worse =
        !prev || (NODE_SEVERITY[n.status] ?? 9) < (NODE_SEVERITY[prev.status] ?? 9) ? n.status : prev.status;
      byService.set(n.service, { status: worse, count: (prev?.count ?? 0) + 1 });
    }
    return [...byService.entries()];
  }, [nodes]);

  const rollbackMembers = useMemo(
    () => nodes.filter((n) => n.rollbackRequired || n.status === "rolled_back" || n.preserved).length,
    [nodes],
  );

  if (nodes.length === 0 && !rollback) return null;

  return (
    <section aria-label="Execution graph summary" className="rounded-xl border border-medha-border bg-white p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="medha-label">
            Execution graph · CEG
          </p>
          <p className="mt-1 text-[13px] text-medha-secondary">
            {nodes.length} node{nodes.length === 1 ? "" : "s"} · {edges.length} edge{edges.length === 1 ? "" : "s"}
            {services.length > 0 ? ` · ${services.length} service${services.length === 1 ? "" : "s"}` : ""}
            {rollback ? ` · ${rollback.rolledBack} rolled back, ${rollback.preserved} preserved` : ""}
          </p>
        </div>
        {graphsHref ? (
          <Link href={graphsHref} className="shrink-0 rounded text-[13px] font-semibold text-medha-accent hover:underline">
            Architecture →
          </Link>
        ) : null}
      </div>
      {services.length > 0 ? (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {services.slice(0, 8).map(([service, info]) => (
            <li
              key={service}
              className="inline-flex items-center gap-1.5 rounded-full border border-medha-border bg-medha-muted/50 px-2.5 py-1 text-[13px]"
              title={`${info.count} node${info.count === 1 ? "" : "s"}${rollbackMembers > 0 ? " · rollback membership recorded" : ""}`}
            >
              <span aria-hidden className="text-[12px]">{statusGlyph(info.status as never)}</span>
              <span className="font-medium text-medha-text">{service}</span>
              <span className="text-medha-tertiary">{labelStatus(info.status as never).toLowerCase()}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {rollback?.simpleExplanation ? (
        <p className="mt-2 text-[13.5px] leading-relaxed text-medha-secondary">{rollback.simpleExplanation}</p>
      ) : null}
      <details
        className="mt-2"
        onToggle={(e) => setExpanded((e.target as HTMLDetailsElement).open)}
      >
        <summary className="cursor-pointer text-[13.5px] font-semibold text-medha-accent">
          Expand graph canvas
        </summary>
        {expanded ? (
          <div className="mt-2">
            <CausalExecutionGraph />
          </div>
        ) : null}
      </details>
    </section>
  );
}

/* --------------------------------- story --------------------------------- */

function RunStory({ snapshot, graphsHref }: { snapshot: DeploymentSnapshot; graphsHref: string | null }) {
  const { viewMode } = useDeployment();
  const technical = viewMode === "technical";
  const evidenceRef = useRef<HTMLDivElement>(null);
  const recoveryRef = useRef<HTMLDivElement>(null);

  const hasChangeIntel = snapshot.changeIntel != null;
  const hasNegotiation = snapshot.negotiation != null || snapshot.constraints.length > 0;
  const hasVerification = snapshot.verification != null || snapshot.critic != null;
  const hasGraph = snapshot.graph.nodes.length > 0;
  const hasRollback = snapshot.rollback != null;
  const failedNodes = snapshot.graph.nodes.filter(
    (n) => n.status === "failed" || n.status === "rolled_back",
  );

  const scrollTo = (ref: React.RefObject<HTMLDivElement | null>) => {
    ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const changeIntel = snapshot.changeIntel;
  const fileCount = changeIntel?.changeset.files.length ?? 0;
  const changeOpen = technical;
  const [changeExpanded, setChangeExpanded] = useState(false);
  const showChangeDetail = technical || changeExpanded;

  return (
    <div className="space-y-3">
      <DecisionCard
        snapshot={snapshot}
        onViewEvidence={() => scrollTo(evidenceRef)}
        onViewRecovery={() => scrollTo(recoveryRef)}
      />
      <SummaryRow snapshot={snapshot} />
      <Pipeline />
      <DiagnosisCard snapshot={snapshot} />

      {hasChangeIntel && changeIntel ? (
        <SectionShell eyebrow="What changed" title="What changed">
          <p className="text-sm text-medha-secondary">
            {fileCount} file{fileCount === 1 ? "" : "s"} changed · risk {changeIntel.risk.level}
          </p>
          <ul className="mt-1.5 space-y-0.5">
            {changeIntel.changeset.files.slice(0, 4).map((f) => (
              <li key={f.path} className="medha-mono truncate text-xs text-medha-text">
                {f.path}{" "}
                <span className="text-medha-tertiary">
                  +{f.added_lines}/−{f.deleted_lines}
                </span>
              </li>
            ))}
          </ul>
          {!changeOpen ? (
            <button
              type="button"
              onClick={() => setChangeExpanded((v) => !v)}
              aria-expanded={changeExpanded}
              className="mt-2 text-sm font-medium text-medha-accent hover:underline"
            >
              {changeExpanded ? "Hide change impact ↑" : "View change impact →"}
            </button>
          ) : null}
          {showChangeDetail ? (
            <div className="mt-2">
              <ChangeImpactPanel analysis={changeIntel} />
            </div>
          ) : null}
        </SectionShell>
      ) : null}

      {hasNegotiation ? <ConstraintNegotiation /> : null}

      {hasVerification ? (
        <div ref={evidenceRef} className="scroll-mt-20">
          <VerificationPanel />
        </div>
      ) : null}

      {hasGraph || hasRollback || failedNodes.length > 0 || technical ? (
        <div ref={recoveryRef} className="scroll-mt-20">
          <CegPreview snapshot={snapshot} graphsHref={graphsHref} />
        </div>
      ) : null}

      {technical ? (
        <>
          <WhatMedhaIsDoing showToggle={false} />
          <RuntimeLogsPanel
            executionMode={snapshot.executionMode}
            runtimeLogs={snapshot.runtimeLogs}
          />
        </>
      ) : null}

      <AgentActivity />
      <LiveSystemTrace />
    </div>
  );
}

/* ------------------------- top-of-page context ------------------------- */

/**
 * Compact run context: project/repo identity, branch, exact source SHA,
 * persisted commit summary + changed files, run times, and the state
 * action (Run analysis / Retry execution). Everything comes from existing
 * records; missing metadata renders as unknown, never fabricated.
 */
function RunContextBar({ deploymentId, projectId }: { deploymentId: string; projectId?: string }) {
  const { snapshot } = useDeployment();
  const router = useRouter();
  const isCanonical = (projectId ?? "").startsWith("prj_");
  const [project, setProject] = useState<Project | null>(null);
  const [record, setRecord] = useState<{
    created_at: string;
    updated_at: string;
    repository_url: string;
    target_sha: string | null;
  } | null>(null);
  const [commit, setCommit] = useState<HistoryCommit | null>(null);
  const [detail, setDetail] = useState<CommitDetail | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchDeployment(deploymentId)
      .then((api) => {
        if (cancelled) return;
        const result = (api.result ?? {}) as Record<string, unknown>;
        setRecord({
          created_at: api.created_at,
          updated_at: api.updated_at,
          repository_url: api.repository_url,
          target_sha: typeof result["target_sha"] === "string" ? (result["target_sha"] as string) : null,
        });
      })
      .catch(() => {
        if (!cancelled) setRecord(null);
      });
    return () => {
      cancelled = true;
    };
  }, [deploymentId]);

  useEffect(() => {
    if (!isCanonical || !projectId) {
      setProject(null);
      return;
    }
    let cancelled = false;
    void fetchProject(projectId)
      .then((p) => {
        if (!cancelled) setProject(p);
      })
      .catch(() => {
        if (!cancelled) setProject(null);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, isCanonical]);

  const sha =
    record?.target_sha ??
    snapshot.changeIntel?.changeset.target_sha ??
    snapshot.changeIntel?.changeset.target_revision ??
    null;

  useEffect(() => {
    if (!isCanonical || !projectId || !sha) {
      setCommit(null);
      setDetail(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const history = await fetchCommitHistory(projectId, { limit: 25 });
        const match =
          (history.commits ?? []).find((c) => c.sha === sha || c.sha.slice(0, 7) === sha.slice(0, 7)) ?? null;
        if (cancelled) return;
        setCommit(match);
        if (match) {
          try {
            setDetail(await fetchCommitDetail(projectId, match.sha));
          } catch {
            if (!cancelled) setDetail(null);
          }
        }
      } catch {
        if (!cancelled) setCommit(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, isCanonical, sha]);

  const legacyRepo = (() => {
    if (!projectId || isCanonical) return null;
    try {
      const decoded = decodeURIComponent(projectId);
      return decoded || null;
    } catch {
      return null;
    }
  })();
  const repo = project?.canonical_url ?? record?.repository_url ?? legacyRepo;
  const headline = commit?.message?.trim().split("\n")[0] ?? null;
  const running = snapshot.runStatus === "running";
  const failed = snapshot.runStatus === "failed";
  const busy = starting || running;

  const startRun = async () => {
    if (!project || busy) return;
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
  };

  return (
    <section aria-label="Run context" className="rounded-xl border border-medha-border bg-white px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p title={repo ?? undefined} className="medha-mono truncate text-[13px] text-medha-secondary">
            {repo ?? "Repository unknown"}
            {project?.branch ? ` · ${project.branch}` : ""}
          </p>
          <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-medha-secondary">
            <div className="flex gap-1.5">
              <dt className="text-medha-tertiary">Revision</dt>
              <dd className="medha-mono font-medium text-medha-text" title={sha ?? undefined}>
                {sha ? (sha.length > 12 ? sha.slice(0, 7) : sha) : "Unknown"}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-medha-tertiary">Started</dt>
              <dd className="font-medium text-medha-text">
                {record ? formatActivity(record.created_at) : "—"}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-medha-tertiary">Duration</dt>
              <dd className="font-medium text-medha-text">{formatDuration(snapshot.durationSeconds)}</dd>
            </div>
          </dl>
          {headline ? (
            <p className="mt-1.5 flex items-start gap-1.5 text-[13.5px] text-medha-text">
              <GitCommitHorizontal className="mt-0.5 h-3.5 w-3.5 shrink-0 text-medha-secondary" aria-hidden />
              <span className="min-w-0">
                <span className="font-medium">{headline}</span>
                {commit?.author ? <span className="text-medha-secondary"> · {commit.author}</span> : ""}
                {detail ? (
                  <span className="text-medha-secondary">
                    {" "}· +{detail.added} −{detail.deleted} across {detail.files.length} file{detail.files.length === 1 ? "" : "s"}
                  </span>
                ) : null}
              </span>
            </p>
          ) : (
            <p className="mt-1.5 text-[13px] text-medha-tertiary">
              {isCanonical ? "Commit summary unavailable for this revision." : "Commit metadata unavailable on this route."}
            </p>
          )}
          {detail && detail.files.length > 0 ? (
            <details>
              <summary className="cursor-pointer text-[13px] font-semibold text-medha-accent">
                Changed files ({detail.files.length})
              </summary>
              <ul className="medha-mono mt-1 max-h-32 space-y-0.5 overflow-y-auto text-[12px] text-medha-secondary">
                {detail.files.slice(0, 20).map((f) => (
                  <li key={f.path} className="flex justify-between gap-2">
                    <span className="truncate">{f.path}</span>
                    <span className="shrink-0">+{f.added} −{f.deleted}</span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          {project ? (
            <button
              type="button"
              onClick={() => void startRun()}
              disabled={busy}
              title={
                running
                  ? "An analysis run is already active — wait for it instead of starting a duplicate."
                  : failed
                    ? "Retry execution for this repository and branch"
                    : "Start a new analysis run for this repository and branch"
              }
              className="inline-flex items-center gap-1.5 rounded-lg bg-medha-accent px-3.5 py-2 text-[13px] font-semibold text-white transition hover:bg-medha-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
            >
              {starting || running ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <PlayCircle className="h-3.5 w-3.5" aria-hidden />}
              {starting ? "Starting…" : running ? "Run active" : failed ? "Retry execution" : "Run analysis"}
            </button>
          ) : (
            <Link
              href="/verify"
              className="inline-flex items-center gap-1.5 rounded-lg bg-medha-accent px-3.5 py-2 text-[13px] font-semibold text-white transition hover:bg-medha-accent-hover"
            >
              <PlayCircle className="h-3.5 w-3.5" aria-hidden /> Run analysis
            </Link>
          )}
          {running ? (
            <p className="text-[12px] text-medha-tertiary">Live run in progress — status updates via SSE.</p>
          ) : null}
          {startError ? (
            <p role="alert" className="max-w-[240px] text-right text-[12.5px] leading-5 text-medha-text">{startError}</p>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function RunBody({ deploymentId, projectId }: { deploymentId: string; projectId?: string }) {
  const { snapshot, openDeployment, hydrating, connectionError } = useDeployment();
  const isHydratedFor = snapshot.deploymentId === deploymentId;
  const failedToLoad =
    isHydratedFor &&
    !hydrating &&
    snapshot.runStatus === "failed" &&
    snapshot.explain.statusLabel === "Failed to load";

  useEffectRef(deploymentId, openDeployment);

  const backHref = projectId ? `/projects/${projectId}/runs` : "/runs";
  const graphsHref = projectId ? `/projects/${projectId}/graphs` : null;

  if (hydrating || !isHydratedFor) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
        <section className="rounded-xl border border-medha-border bg-white p-10 text-center">
          <Loader2 className="mx-auto h-5 w-5 animate-spin text-medha-run" aria-hidden />
          <p className="mt-3 text-[15px] font-semibold text-medha-text">
            Loading verification run…
          </p>
          <p className="mt-1 text-sm text-medha-secondary" aria-live="polite">
            Fetching the decision, evidence, and history.
          </p>
        </section>
      </main>
    );
  }

  if (failedToLoad) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
        <section
          role="alert"
          className="rounded-xl border border-medha-border bg-white p-10 text-center"
        >
          <p className="text-[15px] font-semibold text-medha-text">Unable to load this run.</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-medha-secondary">
            {connectionError || "This run could not be found."}
          </p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <button
              type="button"
              onClick={() => void openDeployment(deploymentId)}
              className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white hover:bg-medha-accent-hover"
            >
              Retry
            </button>
            <Link
              href={backHref}
              className="rounded-lg border border-medha-border bg-white px-4 py-2 text-sm font-medium text-medha-text hover:bg-medha-muted"
            >
              Back to runs
            </Link>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-4xl space-y-3 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1.5 text-sm text-medha-secondary">
          {projectId ? (
            <>
              <Link href={`/projects/${projectId}`} className="inline-flex items-center gap-1 rounded hover:text-medha-text hover:underline">
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Overview
              </Link>
              <span aria-hidden className="text-medha-border-strong">/</span>
            </>
          ) : null}
          <Link href={backHref} className="rounded hover:text-medha-text hover:underline">
            Runs
          </Link>
        </nav>
        <div className="flex flex-wrap items-center gap-2">
          <EnvBadge isDemo={snapshot.isDemo} size="sm" />
          <ExecutionModeBadge mode={snapshot.executionMode} size="sm" />
          <ViewModeToggle />
          <button
            type="button"
            onClick={() => void openDeployment(deploymentId)}
            className="rounded-lg border border-medha-border bg-white px-3 py-1.5 text-xs font-medium text-medha-secondary hover:bg-medha-muted"
          >
            Reload
          </button>
        </div>
      </div>

      <div className="flex items-start gap-3">
        <MedhaFace
          state={faceStateFromRun({
            status: snapshot.runStatus,
            stage: snapshot.explain.currentStage,
            verificationPassed: snapshot.verification?.passed ?? null,
          })}
          size={40}
        />
        <div className="min-w-0">
          <h1 className="text-[28px] font-semibold tracking-tight text-medha-text">
            {runTitle(snapshot, deploymentId)}
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
            <StatusLine snapshot={snapshot} />
            <span className="medha-mono truncate text-[12px] text-medha-tertiary">
              {deploymentId}
            </span>
          </div>
        </div>
      </div>

      <RunContextBar deploymentId={deploymentId} projectId={projectId} />

      <TargetSelectionCard
        snapshot={snapshot}
        deploymentId={deploymentId}
        projectId={projectId}
      />

      {connectionError ? (
        <p
          role="status"
          className="rounded-xl border border-medha-warning/30 bg-medha-warning-soft px-4 py-2.5 text-[13px] text-medha-warning"
        >
          Live updates disconnected. Showing the last saved state.
        </p>
      ) : null}

      <RunStory snapshot={snapshot} graphsHref={graphsHref} />
    </main>
  );
}

// Mode switches never refetch: ViewModeToggle only flips context state.
function useEffectRef(deploymentId: string, openDeployment: (id: string) => Promise<void>) {
  useEffect(() => {
    void openDeployment(deploymentId);
  }, [deploymentId, openDeployment]);
}

export function RunDetailView({ deploymentId, projectId }: { deploymentId: string; projectId?: string }) {
  return (
    <DeploymentProvider>
      <AppShell>
        <RunBody deploymentId={deploymentId} projectId={projectId} />
      </AppShell>
    </DeploymentProvider>
  );
}
