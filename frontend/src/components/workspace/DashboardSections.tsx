"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Container,
  GitCommitHorizontal,
  Info,
} from "lucide-react";
import { Badge, EmptyState, Panel } from "@/components/ui/primitives";
import {
  fetchCommitDetail,
  fetchCommitHistory,
  fetchRepositoryIntel,
  subscribeDeploymentEventsShared,
  type BackendSystemEvent,
  type CommitDetail,
  type HistoryCommit,
  type RepositoryIntelResponse,
  type RunHealth,
  type RunLogLine,
  type RunSummary,
  type RuntimeLogsResponse,
} from "@/lib/api/client";
import { formatActivity } from "@/lib/projects/projects";
import { cn } from "@/lib/ui/cn";

/* ------------------------------- helpers ------------------------------- */

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v : null;
}

function strList(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string" && !!x.trim()) : [];
}

function numList(v: unknown): (string | number)[] {
  return Array.isArray(v) ? v.filter((x): x is string | number => typeof x === "string" || typeof x === "number") : [];
}

function shortSha(v: string | null | undefined): string {
  if (!v) return "—";
  return v.length > 12 ? v.slice(0, 7) : v;
}

/* ============================ LATEST COMMIT ============================ */

interface CommitEvidence {
  commit: HistoryCommit | null;
  detail: CommitDetail | null;
  analyzedSha: string | null;
  stale: boolean;
  unavailable: boolean;
}

function useCommitEvidence(
  projectId: string,
  run: RunSummary | null,
  isCanonical: boolean,
): CommitEvidence & { loading: boolean } {
  const [history, setHistory] = useState<HistoryCommit[] | null>(null);
  const [detail, setDetail] = useState<CommitDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const analyzedSha = run?.target_revision ?? null;

  useEffect(() => {
    if (!isCanonical) {
      setHistory(null);
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setDetail(null);
    void (async () => {
      try {
        const res = await fetchCommitHistory(projectId, { limit: 25 });
        if (cancelled) return;
        setHistory(res.commits ?? []);
        const match = analyzedSha
          ? (res.commits ?? []).find(
              (c) => c.sha === analyzedSha || (analyzedSha && c.sha.startsWith(analyzedSha.slice(0, 7)) && analyzedSha.startsWith(c.sha.slice(0, 7))),
            ) ?? null
          : null;
        const head = match ?? (res.commits ?? [])[0] ?? null;
        if (head) {
          try {
            const d = await fetchCommitDetail(projectId, head.sha);
            if (!cancelled) setDetail(d);
          } catch {
            if (!cancelled) setDetail(null);
          }
        }
      } catch {
        if (!cancelled) setHistory(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, analyzedSha, isCanonical]);

  const commit = useMemo(() => {
    if (!history || history.length === 0) return null;
    if (analyzedSha) {
      const m = history.find(
        (c) => c.sha === analyzedSha || c.sha.slice(0, 7) === analyzedSha.slice(0, 7),
      );
      if (m) return m;
    }
    return history[0] ?? null;
  }, [history, analyzedSha]);

  const stale = !!commit && !!analyzedSha && commit.sha !== analyzedSha && !commit.sha.startsWith(analyzedSha.slice(0, 7));
  return {
    commit,
    detail,
    analyzedSha,
    stale,
    unavailable: !isCanonical || (!loading && history !== null && history.length === 0),
    loading,
  };
}

/** Deterministic, evidence-only implications. "May affect" — never failure claims. */
function deploymentImplications(files: { path: string }[]): string[] {
  const out: string[] = [];
  const paths = files.map((f) => f.path.toLowerCase());
  const has = (...needles: string[]) => paths.some((p) => needles.some((n) => p.includes(n)));
  if (has("dockerfile", "docker-compose", "compose.yml", "compose.yaml")) out.push("Container definition changed — may affect build and deployment.");
  if (has("package.json", "package-lock.json", "requirements.txt", "pyproject.toml", "pom.xml", "go.mod", "gemfile")) out.push("Dependencies changed — may affect build and runtime behavior.");
  if (has(".env", ".env.example", "config/", "settings.py", "application.yml", "appsettings.json")) out.push("Configuration touched — verify environment and secrets wiring.");
  if (has("nginx", ".github/workflows", ".gitlab-ci", "jenkinsfile", "render.yaml", "fly.toml", "procfile")) out.push("Delivery or routing config touched — verify before deploy.");
  if (has("migrations/", "migration", "schema.sql", "alembic/")) out.push("Possible schema change — verify migration safety.");
  return out.slice(0, 3);
}

function summarizeFiles(files: { path: string; added: number; deleted: number }[]): { dirs: string[]; top: typeof files } {
  const dirCount = new Map<string, number>();
  for (const f of files) {
    const dir = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : "(root)";
    dirCount.set(dir, (dirCount.get(dir) ?? 0) + 1);
  }
  const dirs = [...dirCount.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([d]) => d);
  const top = [...files].sort((a, b) => b.added + b.deleted - (a.added + a.deleted)).slice(0, 5);
  return { dirs, top };
}

export function LatestCommitCard({
  projectId,
  run,
  isCanonical,
}: {
  projectId: string;
  run: RunSummary | null;
  isCanonical: boolean;
}) {
  const { commit, detail, analyzedSha, stale, unavailable, loading } = useCommitEvidence(projectId, run, isCanonical);
  const files = useMemo(() => detail?.files ?? [], [detail]);
  const { dirs, top } = useMemo(() => summarizeFiles(files), [files]);
  const implications = useMemo(() => deploymentImplications(files), [files]);
  const message = commit?.message?.trim() || null;
  const headline = message ? message.split("\n")[0] : null;

  return (
    <Panel
      title="Latest commit"
      eyebrow={commit ? `${shortSha(commit.sha)} · ${formatActivity(commit.committed_at)}` : "Source revision"}
      action={
        commit?.github_url ? (
          <a href={commit.github_url} target="_blank" rel="noreferrer" className="rounded text-[13px] font-semibold text-medha-accent hover:underline">
            Open in GitHub →
          </a>
        ) : undefined
      }
    >
      {loading ? (
        <p className="text-[13px] text-medha-secondary">Reading commit metadata…</p>
      ) : !commit ? (
        <p className="text-[13px] text-medha-secondary">
          {unavailable
            ? "Commit history is unavailable for this project (legacy URL route or no recorded history)."
            : "No commit metadata recorded yet — run an analysis first."}
        </p>
      ) : (
        <div key={commit.sha} className="medha-commit-in space-y-2">
          <p className="flex items-start gap-2 text-[14px] font-semibold leading-snug text-medha-text">
            <GitCommitHorizontal className="mt-0.5 h-4 w-4 shrink-0 text-medha-secondary" aria-hidden />
            <span className="min-w-0">{headline ?? "(no commit message recorded)"}</span>
          </p>
          <p className="medha-mono text-[13px] text-medha-secondary">
            {shortSha(commit.sha)}{commit.author ? ` · ${commit.author}` : ""}{commit.branch ? ` · ${commit.branch}` : ""}
            {analyzedSha && analyzedSha !== commit.sha ? ` · analyzed ${shortSha(analyzedSha)}` : " · analyzed revision"}
          </p>
          {stale ? (
            <p className="rounded-lg border border-medha-warning/30 bg-medha-warning-soft px-2.5 py-1.5 text-[13px] text-medha-warning">
              Showing newest known commit; the selected run analyzed {shortSha(analyzedSha)}.
            </p>
          ) : null}
          {message && message.includes("\n") ? (
            <p className="line-clamp-3 text-[13.5px] leading-5 text-medha-secondary">{message.split("\n").slice(1).join(" ").trim()}</p>
          ) : null}
          {detail ? (
            <>
              <p className="text-[13.5px] text-medha-secondary">
                <span className="font-semibold text-medha-text">+{detail.added} −{detail.deleted}</span>
                {" · "}{files.length} file{files.length === 1 ? "" : "s"}
                {dirs.length > 0 ? ` · mostly ${dirs.join(", ")}` : ""}
              </p>
              {implications.length > 0 ? (
                <ul className="space-y-1">
                  {implications.map((i) => (
                    <li key={i} className="flex items-start gap-1.5 text-[13.5px] text-medha-secondary">
                      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-medha-run-ink" aria-hidden /> {i}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[13px] text-medha-tertiary">No deployment-sensitive paths detected in this change.</p>
              )}
              {files.length > 5 ? (
                <details>
                  <summary className="cursor-pointer text-[13.5px] font-semibold text-medha-accent">
                    Show all {files.length} changed files
                  </summary>
                  <ul className="medha-mono mt-1.5 max-h-40 space-y-0.5 overflow-y-auto text-[12px] text-medha-secondary">
                    {files.map((f) => (
                      <li key={f.path} className="flex justify-between gap-2">
                        <span className="truncate">{f.path}</span>
                        <span className="shrink-0">+{f.added} −{f.deleted}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              ) : files.length > 0 ? (
                <ul className="medha-mono space-y-0.5 text-[12px] text-medha-secondary">
                  {top.map((f) => (
                    <li key={f.path} className="flex justify-between gap-2">
                      <span className="truncate">{f.path}</span>
                      <span className="shrink-0">+{f.added} −{f.deleted}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[13px] text-medha-tertiary">Changed-file detail unavailable for this commit.</p>
              )}
            </>
          ) : (
            <p className="text-[13px] text-medha-tertiary">
              {message ? "Changed-file detail unavailable for this commit." : "Richer summary unavailable — showing recorded metadata only."}
            </p>
          )}
        </div>
      )}
    </Panel>
  );
}

/* ========================= REPOSITORY INTELLIGENCE ========================= */

function useRepoIntel(runId: string | null): { intel: RepositoryIntelResponse | null; loading: boolean; missing: boolean } {
  const [intel, setIntel] = useState<RepositoryIntelResponse | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!runId) {
      setIntel(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    void fetchRepositoryIntel(runId)
      .then((v) => {
        if (!cancelled) setIntel(v);
      })
      .catch(() => {
        if (!cancelled) setIntel(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);
  return { intel, loading, missing: !loading && intel === null };
}

function IntelRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2 text-[13.5px]">
      <dt className="w-24 shrink-0 text-medha-tertiary">{label}</dt>
      <dd className="min-w-0 flex-1 text-medha-text">{children}</dd>
    </div>
  );
}

const unknown = <span className="text-medha-tertiary">Unknown</span>;

export function RepoIntelCard({ runId, detailHref }: { runId: string | null; detailHref: string }) {
  const { intel, loading, missing } = useRepoIntel(runId);
  const r = intel?.repository_intelligence as Record<string, unknown> | undefined;
  const tech = (r?.tech_stack ?? {}) as Record<string, unknown>;
  const runtime = (r?.runtime_requirements ?? {}) as Record<string, unknown>;
  const deployCfg = (r?.existing_deploy_config ?? {}) as Record<string, unknown>;
  const services = Array.isArray(r?.components) ? (r?.components as { name?: string; role?: string; suggested_port?: number | null }[]) : [];

  return (
    <Panel
      title="Repository intelligence"
      eyebrow={intel ? `Analyzed ${shortSha(str(r?.commit_sha))}` : "Detected facts"}
      action={<Link href={detailHref} className="rounded text-[13px] font-semibold text-medha-accent hover:underline">Full analysis →</Link>}
    >
      {loading ? (
        <p className="text-[13px] text-medha-secondary">Reading analysis…</p>
      ) : missing || !r ? (
        <p className="text-[13px] text-medha-secondary">
          No repository analysis recorded for this run yet — run an analysis first. Facts are never guessed.
        </p>
      ) : (
        <dl className="space-y-1.5">
          <IntelRow label="Stack">
            {str(tech.language_runtime) ?? str(tech.framework) ? (
              <>
                {[str(tech.language_runtime), str(tech.framework), str(tech.framework_version)].filter(Boolean).join(" · ")}
              </>
            ) : unknown}
          </IntelRow>
          <IntelRow label="Approach">{str(r.proposed_approach) ?? unknown}</IntelRow>
          <IntelRow label="Packages">
            {strList(tech.package_managers).length > 0 ? strList(tech.package_managers).join(", ") : unknown}
          </IntelRow>
          <IntelRow label="Entry points">
            {strList(r.entry_points).length > 0 ? (
              <span className="medha-mono text-[13px]">{strList(r.entry_points).slice(0, 2).join(", ")}</span>
            ) : unknown}
          </IntelRow>
          <IntelRow label="Services">
            {services.length > 0 ? (
              <span>{services.slice(0, 3).map((s) => s.name ?? "?").join(", ")}{services.length > 3 ? ` +${services.length - 3}` : ""}</span>
            ) : unknown}
          </IntelRow>
          <IntelRow label="Ports">
            {numList(runtime.suggested_ports).length > 0 ? (
              <span className="medha-mono text-[13px]">{numList(runtime.suggested_ports).join(", ")}</span>
            ) : unknown}
          </IntelRow>
          <IntelRow label="Manifests">
            {strList(deployCfg.manifests_examined).length > 0 ? (
              <span className="medha-mono text-[13px]">
                {(strList(deployCfg.manifests_examined).includes("Dockerfile") || (deployCfg.has_dockerfile as boolean) ? "Dockerfile ✓ · " : "")}
                {strList(deployCfg.manifests_examined).slice(0, 3).join(", ")}
              </span>
            ) : unknown}
          </IntelRow>
          {strList(r.unknowns).length > 0 ? (
            <p className="border-t border-medha-border pt-1.5 text-[13px] text-medha-tertiary">{strList(r.unknowns)[0]}</p>
          ) : null}
          {strList(r.unsupported).length > 0 ? (
            <p className="flex items-start gap-1.5 text-[13px] text-medha-warning">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> {strList(r.unsupported)[0]}
            </p>
          ) : null}
        </dl>
      )}
    </Panel>
  );
}

/* ============================= DEPLOYMENT HEALTH ============================= */

export type DeployState = "healthy" | "unhealthy" | "unverified" | "not-deployed" | "unknown";

export function deployStateOf(run: RunSummary | null, health: RunHealth | null): { state: DeployState; label: string; tone: "success" | "warning" | "error" | "info" | "neutral" } {
  const h = (health?.health_status ?? "").toLowerCase();
  if (h === "healthy") return { state: "healthy", label: "Healthy", tone: "success" };
  if (h === "unhealthy" || h === "failed") return { state: "unhealthy", label: "Unhealthy", tone: "error" };
  if (h === "running" || h === "degraded") return { state: "unverified", label: "Running — health unverified", tone: "warning" };
  if (h === "not_deployed" || h === "not-deployed" || h === "stopped") return { state: "not-deployed", label: "Not deployed", tone: "neutral" };
  // Never equate a finished workflow or a running container with health.
  if (run && ["queued", "started", "running", "executing"].includes(run.status)) return { state: "unknown", label: "Deploying", tone: "info" };
  return { state: "unknown", label: "Unknown", tone: "neutral" };
}

export function DeployHealthCard({
  run,
  health,
  runtimeLogs,
  detailHref,
}: {
  run: RunSummary | null;
  health: RunHealth | null;
  runtimeLogs: RuntimeLogsResponse | null;
  detailHref: string;
}) {
  const { label, tone } = deployStateOf(run, health);
  const stdoutTail = runtimeLogs?.stdout?.trim().split("\n").slice(-3).join("\n") ?? "";
  const stderrTail = runtimeLogs?.stderr?.trim().split("\n").slice(-3).join("\n") ?? "";

  return (
    <Panel
      title="Deployment health"
      eyebrow="Observed evidence only"
      action={<Link href={detailHref} className="rounded text-[13px] font-semibold text-medha-accent hover:underline">Deployments →</Link>}
    >
      <div key={label} className="medha-health-in space-y-2">
        <p>
          <Badge tone={tone}>{label}</Badge>
          {health?.is_demo ? <span className="ml-2 text-[12px] font-semibold text-medha-tertiary">DEMO/MOCK</span> : null}
        </p>
        {health?.reason ? <p className="text-[13.5px] text-medha-secondary">{health.reason}</p> : null}
        <dl className="space-y-1.5">
          <IntelRow label="Checked">
            {health?.checked_at ? formatActivity(health.checked_at) : <span className="text-medha-tertiary">No health check recorded</span>}
          </IntelRow>
          <IntelRow label="Container">
            {runtimeLogs?.container || health?.container ? (
              <span className="medha-mono text-[13px]">{runtimeLogs?.container ?? health?.container}</span>
            ) : (
              <span className="text-medha-tertiary">No container observed</span>
            )}
          </IntelRow>
          {run?.duration_seconds != null ? (
            <IntelRow label="Run time">{`${run.duration_seconds}s`}</IntelRow>
          ) : null}
        </dl>
        {stderrTail ? (
          <pre className="medha-mono max-h-20 overflow-y-auto rounded-lg border border-medha-danger/25 bg-medha-danger-soft p-2 text-[12px] leading-4 text-medha-danger">{stderrTail}</pre>
        ) : stdoutTail ? (
          <pre className="medha-mono max-h-20 overflow-y-auto rounded-lg border border-medha-border bg-medha-muted p-2 text-[12px] leading-4 text-medha-secondary">{stdoutTail}</pre>
        ) : (
          <p className="text-[13px] text-medha-tertiary">No recent container logs observed.</p>
        )}
        {!health ? (
          <p className="border-t border-medha-border pt-1.5 text-[13px] text-medha-tertiary">
            Health monitoring has not reported for this run — a running container is not shown as healthy.
          </p>
        ) : null}
      </div>
    </Panel>
  );
}

/* ========================= LATEST EVENTS & FINDINGS ========================= */

interface UiEvent {
  key: string;
  ts: string;
  label: string;
  tone: "success" | "warning" | "error" | "info" | "neutral";
  detail: string | null;
}

function eventTone(l: RunLogLine): UiEvent["tone"] {
  if (l.level === "error") return "error";
  if (l.level === "warning") return "warning";
  const t = (l.type ?? "").toLowerCase();
  if (t.includes("completed") || t.includes("passed")) return "success";
  if (t.includes("started") || t.includes("running")) return "info";
  return "neutral";
}

function eventLabel(l: RunLogLine): string {
  const t = (l.type ?? "").toLowerCase();
  const stage = (l.stage ?? "").toLowerCase();
  if (t.includes("stage.completed")) return `${l.stage ?? "Stage"} completed`;
  if (t.includes("stage.started")) return `${l.stage ?? "Stage"} started`;
  if (t.includes("rollback")) return "Rollback recorded";
  if (stage.includes("verif")) return l.level === "error" ? "Verification failed" : "Verification update";
  if (stage.includes("cnp") || stage.includes("negot") || stage.includes("mediat")) return "Negotiation update";
  if (stage.includes("execut")) return "Execution update";
  if (stage.includes("analy")) return "Analysis update";
  if (stage.includes("deploy") || stage.includes("health")) return "Deployment update";
  if (l.level === "error") return "Failure recorded";
  if (l.level === "warning") return "Warning recorded";
  return l.stage ?? "Event";
}

const MEANINGFUL = /stage\.|verif|cnp|negot|execut|deploy|health|rollback|critic|approv|fail|error|warn|plan|analy/i;

function deriveEvents(logs: RunLogLine[], limit = 8): UiEvent[] {
  const seen = new Set<string>();
  const out: UiEvent[] = [];
  const ordered = [...logs].reverse();
  for (const l of ordered) {
    const hay = `${l.type} ${l.stage} ${l.source} ${l.message} ${l.level}`;
    if (!MEANINGFUL.test(hay)) continue;
    const key = `${l.ts}|${l.message}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ key, ts: l.ts, label: eventLabel(l), tone: eventTone(l), detail: l.message || null });
    if (out.length >= limit) break;
  }
  return out;
}

const TONE_DOT: Record<UiEvent["tone"], string> = {
  success: "bg-medha-success",
  warning: "bg-medha-warning",
  error: "bg-medha-danger",
  info: "bg-medha-run",
  neutral: "bg-medha-border-strong",
};

export function EventsCard({ runId, logs }: { runId: string | null; logs: RunLogLine[] }) {
  const [live, setLive] = useState<UiEvent[]>([]);
  const seenRef = useRef<Set<string>>(new Set());
  const base = useMemo(() => deriveEvents(logs), [logs]);

  // Live SSE append with replay dedupe; scroll position untouched (no autoscroll).
  useEffect(() => {
    seenRef.current = new Set(logs.map((l) => `${l.ts}|${l.message}`));
    setLive([]);
    if (!runId) return;
    const sub = subscribeDeploymentEventsShared(runId, {
      onEvent: (e: BackendSystemEvent) => {
        const raw = e as unknown as Record<string, unknown>;
        const msg = str(raw.message) ?? str(raw.simple) ?? "";
        const ts = str(raw.ts) ?? new Date().toISOString();
        const key = `${ts}|${msg}`;
        if (!msg || seenRef.current.has(key)) return;
        seenRef.current.add(key);
        const line: RunLogLine = {
          ts,
          level: str(raw.level) ?? "info",
          source: str(raw.source) ?? "stream",
          message: msg,
          type: str(raw.type) ?? "event",
          stage: str(raw.stage),
          status: null,
          is_demo: false,
        };
        const hay = `${line.type} ${line.stage} ${line.source} ${line.message}`;
        if (!MEANINGFUL.test(hay)) return;
        setLive((prev) => [{ key, ts, label: eventLabel(line), tone: eventTone(line), detail: msg }, ...prev].slice(0, 8));
      },
      onTerminal: () => undefined,
      onError: () => undefined,
    });
    return () => sub.close();
  }, [runId, logs]);

  const events = useMemo(() => {
    const keys = new Set(live.map((e) => e.key));
    return [...live, ...base.filter((e) => !keys.has(e.key))].slice(0, 8);
  }, [live, base]);

  if (events.length === 0) {
    return (
      <Panel title="Latest events & findings" eyebrow="Chronological">
        <EmptyState title="No events yet" body="Meaningful backend events will appear here once the run produces them." />
      </Panel>
    );
  }

  return (
    <Panel title="Latest events & findings" eyebrow={`${events.length} recent`}>
      <ol className="space-y-1.5">
        {events.map((e, i) => (
          <li
            key={e.key}
            className={cn("medha-event-in flex items-start gap-2 rounded-lg px-2 py-1.5", i === 0 && live.length > 0 ? "bg-medha-accent-soft" : "hover:bg-medha-surface-muted")}
            style={{ animationDelay: `${Math.min(i * 30, 150)}ms` }}
          >
            <span className={cn("status-dot mt-1.5", TONE_DOT[e.tone])} aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-baseline justify-between gap-x-2 text-[13.5px]">
                <span className="font-semibold text-medha-text">{e.label}</span>
                <time className="shrink-0 text-[12px] text-medha-tertiary">{formatActivity(e.ts)}</time>
              </p>
              {e.detail ? <p className="mt-0.5 line-clamp-2 break-words text-[13px] text-medha-secondary">{e.detail}</p> : null}
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}

/* ============================ FINDINGS (COMPACT) ============================ */

export function FindingsStrip({
  findings,
}: {
  findings: { id: string; tone: "error" | "warning" | "info"; title: string; body: string; action?: { label: string; href: string } }[];
}) {
  if (findings.length === 0) {
    return (
      <p className="flex items-center gap-1.5 text-[13px] font-medium text-medha-success-ink">
        <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden /> No outstanding issues for this run.
      </p>
    );
  }
  return (
    <ol className="space-y-1.5">
      {findings.slice(0, 4).map((f) => (
        <li
          key={f.id}
          className={cn(
            "rounded-lg border px-2.5 py-1.5",
            f.tone === "error" && "border-medha-danger/30 bg-medha-danger-soft",
            f.tone === "warning" && "border-medha-warning/30 bg-medha-warning-soft",
            f.tone === "info" && "border-medha-run/25 bg-medha-run-soft",
          )}
        >
          <p className="flex items-center gap-1.5 text-[13.5px] font-semibold text-medha-text">
            {f.tone === "error" ? <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-medha-danger" aria-hidden /> : null}
            {f.title}
          </p>
          <p className="mt-0.5 line-clamp-2 text-[13px] text-medha-secondary">{f.body}</p>
          {f.action ? (
            <Link href={f.action.href} className="mt-0.5 inline-block rounded text-[13px] font-semibold text-medha-accent hover:underline">
              {f.action.label}
            </Link>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

export function DeployStatusIcon({ state }: { state: DeployState }) {
  if (state === "healthy") return <CheckCircle2 className="h-3.5 w-3.5 text-medha-success" aria-hidden />;
  if (state === "unhealthy") return <AlertTriangle className="h-3.5 w-3.5 text-medha-danger" aria-hidden />;
  return <Container className="h-3.5 w-3.5 text-medha-secondary" aria-hidden />;
}
