"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  Copy,
  Filter,
  FolderGit2,
  FolderKanban,
  GitBranch,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ConnectRepoDialog } from "@/components/workspace/ConnectRepoDialog";
import { Dialog } from "@/components/ui/primitives";
import {
  createProjectRun,
  deleteProject,
  disconnectProject,
} from "@/lib/api/client";
import {
  PROJECT_CARD_STATUS_META,
  canonicalRepoKey,
  filterProjectsByStatus,
  formatActivityCompact,
  isRunningStatus,
  projectCardStatus,
  sortProjects,
  useProjects,
  type ProjectCardStatus,
  type ProjectSort,
  type ProjectSummary,
} from "@/lib/projects/projects";

/* Uses the shared MEDHA design tokens: text, secondary, tertiary, accent,
   success, warning, danger, and their soft variants. */

const SORT_OPTIONS: { id: ProjectSort; label: string }[] = [
  { id: "recent", label: "Recently active" },
  { id: "name", label: "Name" },
  { id: "status", label: "Status" },
];

type DisplayTone = "danger" | "warning" | "info" | "neutral";

function projectStatusDisplay(project: ProjectSummary): {
  label: string;
  tone: DisplayTone;
} {
  const latest = project.latest;
  if (latest && isRunningStatus(latest.status)) {
    return { label: "Running", tone: "info" };
  }
  if (latest?.status === "failed") {
    return { label: "Failed", tone: "danger" };
  }
  if (latest?.status === "awaiting_approval") {
    return { label: "Awaiting approval", tone: "warning" };
  }
  if (latest?.status === "partial_recovery") {
    return { label: "Partial recovery", tone: "warning" };
  }
  if (latest?.status === "cancelled") {
    return { label: "Cancelled", tone: "warning" };
  }
  if (!latest || project.totalRuns === 0) {
    if (project.connectionStatus === "failed") {
      return { label: "Connection failed", tone: "warning" };
    }
    if (project.connectionStatus === "disconnected") {
      return { label: "Disconnected", tone: "neutral" };
    }
    if (project.connectionStatus === "pending") {
      return { label: "Pending", tone: "neutral" };
    }
    return { label: "No runs yet", tone: "neutral" };
  }
  if (project.attention.length > 0) {
    return { label: "Needs attention", tone: "warning" };
  }
  // Completion is not health: keep this state neutral unless evidence says otherwise.
  return { label: "Completed", tone: "neutral" };
}

const BADGE_TONE: Record<DisplayTone, string> = {
  danger: "border-medha-danger/30 bg-medha-danger-soft text-medha-danger",
  warning: "border-medha-warning/30 bg-medha-warning-soft text-medha-warning",
  info: "border-medha-accent/25 bg-medha-accent-soft text-medha-accent-hover",
  neutral: "border-medha-border bg-medha-surface-muted text-medha-secondary",
};

function StatusBadge({
  display,
}: {
  display: ReturnType<typeof projectStatusDisplay>;
}) {
  return (
    <span
      className={`inline-flex max-w-full shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-semibold whitespace-nowrap ${BADGE_TONE[display.tone]}`}
    >
      <span
        aria-hidden
        className={`h-1.5 w-1.5 shrink-0 rounded-full bg-current ${display.label === "Running" ? "motion-safe:animate-pulse" : ""}`}
      />
      {display.label}
    </span>
  );
}

interface CardActions {
  onReanalyze: (p: ProjectSummary) => void;
  onDisconnect: (p: ProjectSummary) => void;
  onDelete: (p: ProjectSummary) => void;
  acting: string | null;
}

function CardMenu({ project, actions }: { project: ProjectSummary; actions: CardActions }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointer(e: PointerEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function copyUrl() {
    try {
      await navigator.clipboard.writeText(project.repositoryUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  const itemCls =
    "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-medha-secondary hover:bg-medha-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-medha-accent disabled:cursor-not-allowed disabled:opacity-50";
  const busy = actions.acting != null && actions.acting.startsWith(`${project.id}:`);
  // Legacy URL groups are read-only compatibility rows: only actions that
  // genuinely work are shown (never a dead menu item).
  const canonical = !project.legacy && project.projectId != null;
  const connected = canonical && project.connectionStatus === "connected";

  return (
    <div ref={wrapRef} className="relative shrink-0">
      <button
        ref={buttonRef}
        type="button"
        aria-label={`Actions for ${project.name}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="rounded-md p-1.5 text-medha-secondary hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label={`Actions for ${project.name}`}
          className="absolute right-0 top-full z-30 mt-1 w-52 rounded-lg border border-medha-border bg-white p-1 shadow-[0_8px_24px_rgba(17,24,39,0.12)]"
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
            e.preventDefault();
            const items = Array.from(
              e.currentTarget.querySelectorAll<HTMLElement>(
                '[role="menuitem"]:not([disabled])',
              ),
            );
            if (items.length === 0) return;
            const index = items.indexOf(document.activeElement as HTMLElement);
            const next =
              e.key === "ArrowDown"
                ? (index + 1) % items.length
                : (index - 1 + items.length) % items.length;
            items[next]?.focus();
          }}
        >
          <Link
            role="menuitem"
            href={`/projects/${project.id}`}
            className={itemCls}
            onClick={() => setOpen(false)}
          >
            Open project
          </Link>
          <Link
            role="menuitem"
            href={`/projects/${project.id}/runs`}
            className={itemCls}
            onClick={() => setOpen(false)}
          >
            View runs
          </Link>
          {canonical ? (
            <button
              type="button"
              role="menuitem"
              className={itemCls}
              disabled={busy || !connected}
              title={connected ? "Start a new analysis run" : "Reconnect the repository before re-analyzing"}
              onClick={() => {
                setOpen(false);
                actions.onReanalyze(project);
              }}
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              {busy && actions.acting === `${project.id}:reanalyze` ? "Starting…" : "Re-analyze repository"}
            </button>
          ) : null}
          {canonical ? (
            <Link
              role="menuitem"
              href={`/projects/${project.id}/settings`}
              className={itemCls}
              onClick={() => setOpen(false)}
            >
              Project settings
            </Link>
          ) : null}
          <button type="button" role="menuitem" className={itemCls} onClick={() => void copyUrl()}>
            {copied ? (
              <Check className="h-3.5 w-3.5 text-medha-success-ink" aria-hidden />
            ) : (
              <Copy className="h-3.5 w-3.5" aria-hidden />
            )}
            {copied ? "Copied URL" : "Copy repository URL"}
          </button>
          {canonical ? <div role="separator" className="my-1 h-px bg-medha-border" /> : null}
          {canonical && project.connectionStatus !== "disconnected" ? (
            <button
              type="button"
              role="menuitem"
              className={itemCls}
              disabled={busy}
              onClick={() => {
                setOpen(false);
                actions.onDisconnect(project);
              }}
            >
              Disconnect repository
            </button>
          ) : null}
          {canonical ? (
            <button
              type="button"
              role="menuitem"
              className={`${itemCls} text-medha-danger hover:bg-medha-danger-soft`}
              disabled={busy}
              onClick={() => {
                setOpen(false);
                actions.onDelete(project);
              }}
            >
              Delete project
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ProjectCard({ project, actions }: { project: ProjectSummary; actions: CardActions }) {
  const display = projectStatusDisplay(project);
  const identity =
    project.repoOwner && project.repoName
      ? `${project.repoOwner}/${project.repoName}`
      : canonicalRepoKey(project.repositoryUrl) ??
        project.repositoryUrl.replace(/^https?:\/\//, "").replace(/\.git$/, "");
  const activity = formatActivityCompact(project.lastActivity);
  const activityTitle = project.lastActivity
    ? new Date(project.lastActivity).toLocaleString()
    : undefined;
  const base = `/projects/${project.id}`;

  return (
    <article
      aria-label={project.name}
      className="group relative flex h-full flex-col rounded-lg border border-medha-border bg-white p-4 shadow-[0_1px_2px_rgba(17,24,39,0.06)] transition-colors hover:border-medha-border-strong focus-within:border-medha-accent focus-within:ring-2 focus-within:ring-medha-accent/20 lg:aspect-square lg:h-auto lg:self-start"
    >
      <div className="flex items-start justify-between gap-2">
        <span
          aria-hidden
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-medha-accent-soft text-medha-accent"
        >
          <FolderGit2 className="h-4 w-4" />
        </span>
        <div className="relative z-20">
          <CardMenu project={project} actions={actions} />
        </div>
      </div>

      <h2 className="mt-3 min-w-0 text-[17px] font-semibold leading-snug tracking-tight text-medha-text">
        <Link
          href={base}
          title={project.name}
          className="block outline-none after:absolute after:inset-0 after:z-[1] after:rounded-lg after:content-['']"
        >
          <span className="line-clamp-2">{project.name}</span>
        </Link>
      </h2>
      <p className="mt-1 flex min-w-0 items-center gap-1.5 text-[12px] text-medha-secondary">
        <span className="min-w-0 truncate font-mono" title={identity}>
          {identity}
        </span>
        {project.branch ? (
          <span
            className="inline-flex min-w-0 max-w-[45%] shrink-0 items-center gap-1 text-medha-tertiary"
            title={`Branch ${project.branch}`}
          >
            <GitBranch className="h-3 w-3 shrink-0" aria-hidden />
            <span className="truncate font-mono">{project.branch}</span>
          </span>
        ) : null}
      </p>

      {project.summary ? (
        <p className="mt-3 line-clamp-2 text-[13px] leading-5 text-medha-secondary">
          {project.summary}
        </p>
      ) : null}

      <div className="mt-auto flex min-w-0 items-center justify-between gap-2 pt-3">
        <StatusBadge display={display} />
        {activity ? (
          <time
            dateTime={project.lastActivity ?? undefined}
            title={activityTitle}
            className="min-w-0 truncate text-[11.5px] tabular-nums text-medha-tertiary"
          >
            {activity}
          </time>
        ) : null}
      </div>
    </article>
  );
}

function SkeletonGrid() {
  return (
    <div
      aria-label="Loading projects"
      role="status"
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
    >
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className="flex h-full flex-col rounded-lg border border-medha-border bg-white p-4 lg:aspect-square lg:h-auto lg:self-start"
        >
          <div className="flex items-start justify-between">
            <div className="h-8 w-8 rounded-md bg-medha-surface-muted" />
            <div className="h-6 w-6 rounded-md bg-medha-surface-muted" />
          </div>
          <div className="mt-3 h-4 w-3/4 rounded bg-medha-surface-muted" />
          <div className="mt-2 h-3 w-1/2 rounded bg-medha-surface-muted" />
          <div className="mt-3 h-3 w-full rounded bg-medha-surface-muted" />
          <div className="mt-1 h-3 w-2/3 rounded bg-medha-surface-muted" />
          <div className="mt-auto flex items-center justify-between gap-2 pt-3">
            <div className="h-5 w-24 rounded-full bg-medha-surface-muted" />
            <div className="h-3 w-20 rounded bg-medha-surface-muted" />
          </div>
        </div>
      ))}
    </div>
  );
}

type ConfirmState =
  | { kind: "disconnect"; project: ProjectSummary }
  | { kind: "delete"; project: ProjectSummary };

export function ProjectHub() {
  const { projects, loading, error, backendReachable, refresh } = useProjects();
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<ProjectCardStatus | "all">("all");
  const [sort, setSort] = useState<ProjectSort>("recent");
  const [filterOpen, setFilterOpen] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const [acting, setActing] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const filterWrapRef = useRef<HTMLDivElement>(null);
  const filterButtonRef = useRef<HTMLButtonElement>(null);

  const activeSet = useMemo(
    () =>
      new Set<ProjectCardStatus>(statusFilter === "all" ? [] : [statusFilter]),
    [statusFilter],
  );

  const visible = useMemo(
    () => sortProjects(filterProjectsByStatus(projects, query, activeSet), sort),
    [projects, query, activeSet, sort],
  );

  const counts = useMemo(() => {
    const byStatus: Record<ProjectCardStatus, number> = {
      attention: 0,
      running: 0,
      completed: 0,
      no_runs: 0,
    };
    for (const p of projects) byStatus[projectCardStatus(p)] += 1;
    return { total: projects.length, byStatus };
  }, [projects]);

  useEffect(() => {
    if (!filterOpen) return;
    function onPointer(e: PointerEvent) {
      if (filterWrapRef.current && !filterWrapRef.current.contains(e.target as Node)) {
        setFilterOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setFilterOpen(false);
        filterButtonRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [filterOpen]);

  function clearAll() {
    setQuery("");
    setStatusFilter("all");
  }

  async function reanalyze(project: ProjectSummary) {
    if (!project.projectId) return;
    setActing(`${project.id}:reanalyze`);
    setActionError(null);
    try {
      await createProjectRun(project.projectId, {});
      await refresh();
    } catch (err) {
      const code = err instanceof Error && "code" in err ? String((err as { code?: unknown }).code ?? "") : "";
      setActionError(
        code === "DEPLOYMENT_BUSY"
          ? "Another analysis is already running (V1 runs one at a time). Try again once it finishes."
          : code === "PROJECT_NOT_CONNECTED"
            ? `“${project.name}” is not connected, so no analysis can start. Verify or reconnect it first.`
            : err instanceof Error
              ? err.message
              : "Could not start a new analysis.",
      );
    } finally {
      setActing(null);
    }
  }

  async function confirmAction() {
    if (!confirm) return;
    const pid = confirm.project.projectId;
    if (pid == null) return;
    const { kind, project } = confirm;
    const id: string = pid;
    setActing(`${project.id}:${kind}`);
    setActionError(null);
    try {
      if (kind === "disconnect") await disconnectProject(id);
      else await deleteProject(id);
      setConfirm(null);
      await refresh();
    } catch (err) {
      const code = err instanceof Error && "code" in err ? String((err as { code?: unknown }).code ?? "") : "";
      setActionError(
        code === "ACTIVE_RUNS"
          ? `“${project.name}” has a run still in flight, so deletion was refused to protect it. Disconnect instead, or retry once the run finishes.`
          : err instanceof Error
            ? err.message
            : `Could not ${kind} this project.`,
      );
      setConfirm(null);
    } finally {
      setActing(null);
    }
  }

  const actions: CardActions = useMemo(
    () => ({
      onReanalyze: (p) => void reanalyze(p),
      onDisconnect: (p) => {
        setActionError(null);
        setConfirm({ kind: "disconnect", project: p });
      },
      onDelete: (p) => {
        setActionError(null);
        setConfirm({ kind: "delete", project: p });
      },
      acting,
    }),
    // reanalyze/refresh are stable enough per render; acting drives busy UI.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [acting],
  );

  const failed = !!error && !backendReachable && !loading;
  const hasCache = projects.length > 0;
  const showSkeletons = loading && !hasCache;

  return (
    <AppShell>
      {/* Full-bleed bright workspace inside AppShell's padded main. */}
      <div className="-m-4 min-h-[calc(100svh-3.5rem)] bg-medha-canvas p-4 sm:-m-6 sm:p-6 lg:-m-8 lg:p-8">
        <div className="mx-auto w-full max-w-[1400px]">
          {/* Header */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <h1 className="text-[22px] font-semibold leading-tight tracking-tight text-medha-text">
                Project Hub
              </h1>
            </div>
            <button
              type="button"
              onClick={() => setConnecting(true)}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-medha-accent px-3.5 py-2 text-sm font-semibold text-white shadow-[0_1px_2px_rgba(37,99,235,0.4)] transition hover:bg-medha-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
            >
              <Plus className="h-4 w-4" aria-hidden /> New project
            </button>
          </div>

          {/* Compact toolbar: search, status filter menu, and sorting. */}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <div className="relative w-full sm:w-[360px]">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-medha-tertiary"
                aria-hidden
              />
              <label htmlFor="projects-search" className="sr-only">
                Search projects
              </label>
              <input
                id="projects-search"
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search projects..."
                autoComplete="off"
                className="w-full rounded-lg border border-medha-border bg-white py-2 pl-9 pr-8 text-sm text-medha-text shadow-[0_1px_2px_rgba(17,24,39,0.05)] placeholder:text-medha-tertiary focus:border-medha-accent focus:outline-none focus:ring-2 focus:ring-medha-accent/25"
              />
              {query ? (
                <button
                  type="button"
                  aria-label="Clear search"
                  onClick={() => setQuery("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-medha-secondary hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
                >
                  <X className="h-3.5 w-3.5" aria-hidden />
                </button>
              ) : null}
            </div>

            <div className="flex items-center gap-2">
              <div ref={filterWrapRef} className="relative">
                <button
                  ref={filterButtonRef}
                  type="button"
                  aria-haspopup="dialog"
                  aria-expanded={filterOpen}
                  aria-controls="projects-filter-popover"
                  onClick={() => setFilterOpen((v) => !v)}
                  className={`inline-flex items-center gap-1.5 rounded-lg border px-3.5 py-2 text-sm font-medium transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent ${
                    statusFilter !== "all"
                      ? "border-medha-accent bg-medha-accent-soft text-medha-accent-hover"
                      : "border-medha-border bg-white text-medha-secondary hover:bg-medha-surface-muted"
                  }`}
                >
                  <Filter className="h-4 w-4" aria-hidden />
                  Filter
                </button>

                {filterOpen ? (
                  <div
                    id="projects-filter-popover"
                    role="dialog"
                    aria-label="Filter projects"
                    className="absolute left-0 top-full z-40 mt-2 w-60 max-w-[calc(100vw-2rem)] rounded-lg border border-medha-border bg-white p-4 shadow-[0_8px_24px_rgba(17,24,39,0.12)]"
                  >
                    <fieldset>
                      <legend className="medha-label">Status</legend>
                      <div className="mt-2 space-y-0.5">
                        {[
                          { id: "all" as const, label: "All projects", count: counts.total },
                          ...PROJECT_CARD_STATUS_META.map((s) => ({
                            ...s,
                            count: counts.byStatus[s.id],
                          })),
                        ].map((option) => (
                          <label
                            key={option.id}
                            className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] text-medha-secondary hover:bg-medha-canvas focus-within:outline focus-within:outline-2 focus-within:outline-medha-accent"
                          >
                            <input
                              type="radio"
                              name="projects-status"
                              checked={statusFilter === option.id}
                              onChange={() => setStatusFilter(option.id)}
                              className="h-3.5 w-3.5 shrink-0 cursor-pointer accent-medha-accent"
                            />
                            <span className="flex-1">{option.label}</span>
                            <span className="text-[12px] tabular-nums text-medha-tertiary">
                              {option.count}
                            </span>
                          </label>
                        ))}
                      </div>
                    </fieldset>

                    <div className="mt-3 flex items-center justify-between border-t border-medha-border pt-3">
                      <button
                        type="button"
                        onClick={() => {
                          setStatusFilter("all");
                          setSort("recent");
                        }}
                        disabled={statusFilter === "all" && sort === "recent"}
                        className="rounded-md px-2 py-1 text-[13px] font-medium text-medha-secondary hover:bg-medha-surface-muted hover:text-medha-text disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
                      >
                        Reset
                      </button>
                      <button
                        type="button"
                        onClick={() => setFilterOpen(false)}
                        className="rounded-md bg-medha-accent px-3 py-1.5 text-[13px] font-semibold text-white hover:bg-medha-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
                      >
                        Show {visible.length}
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>

              <label htmlFor="projects-sort" className="sr-only">
                Sort projects
              </label>
              <select
                id="projects-sort"
                value={sort}
                onChange={(e) => setSort(e.target.value as ProjectSort)}
                className="w-[170px] truncate rounded-lg border border-medha-border bg-white px-3 py-2 text-sm text-medha-secondary focus:border-medha-accent focus:outline-none focus:ring-2 focus:ring-medha-accent/25"
              >
                {SORT_OPTIONS.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Error banner (compact; preserves toolbar + cached grid) */}
          {failed ? (
            <div
              role="alert"
              className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-[13px]"
            >
              <p className="min-w-0 flex-1 text-medha-danger">
                <span className="font-semibold">Couldn&apos;t refresh projects. </span>
                <span className="break-words">{error ?? "The backend is unreachable."}</span>
                {hasCache ? <span> Showing last known projects.</span> : null}
              </p>
              <button
                type="button"
                onClick={() => void refresh()}
                className="shrink-0 rounded-md border border-medha-danger/30 bg-white px-3 py-1.5 text-[12.5px] font-semibold text-medha-danger hover:bg-medha-danger-soft focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
              >
                Retry
              </button>
            </div>
          ) : null}

          {/* Action errors (mutations: re-analyze, disconnect, delete) */}
          {actionError ? (
            <div
              role="alert"
              className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-[13px]"
            >
              <p className="min-w-0 flex-1 break-words text-medha-danger">{actionError}</p>
              <button
                type="button"
                aria-label="Dismiss error"
                onClick={() => setActionError(null)}
                className="shrink-0 rounded-md p-1 text-medha-danger hover:bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>
          ) : null}

          {/* Content */}
          <div className="mt-4">
            {showSkeletons ? (
              <SkeletonGrid />
            ) : failed && !hasCache ? (
              <div className="flex flex-col items-center rounded-lg border border-medha-border bg-white px-6 py-12 text-center">
                <span
                  aria-hidden
                  className="flex h-11 w-11 items-center justify-center rounded-lg bg-medha-surface-muted text-medha-secondary"
                >
                  <FolderKanban className="h-5 w-5" />
                </span>
                <p className="mt-3 text-[15px] font-semibold text-medha-text">
                  Projects couldn&apos;t load
                </p>
                <p className="mt-1 max-w-md text-sm leading-relaxed text-medha-secondary">
                  The request failed before any project data arrived. Check that the
                  backend is running, then try again.
                </p>
                <button
                  type="button"
                  onClick={() => void refresh()}
                  className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white hover:bg-medha-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
                >
                  Retry
                </button>
              </div>
            ) : counts.total === 0 ? (
              <div className="flex flex-col items-center rounded-lg border border-medha-border bg-white px-6 py-12 text-center">
                <span
                  aria-hidden
                  className="flex h-11 w-11 items-center justify-center rounded-lg bg-medha-accent-soft text-medha-accent"
                >
                  <FolderKanban className="h-5 w-5" />
                </span>
                <p className="mt-3 text-[15px] font-semibold text-medha-text">No projects yet</p>
                <p className="mt-1 max-w-md text-sm leading-relaxed text-medha-secondary">
                  Connect a GitHub repository to record its first analysis. Only
                  verified, readable repositories appear here — nothing simulated.
                </p>
                <button
                  type="button"
                  onClick={() => setConnecting(true)}
                  className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white hover:bg-medha-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
                >
                  <Plus className="h-4 w-4" aria-hidden /> New project
                </button>
              </div>
            ) : visible.length === 0 ? (
              <div className="flex flex-col items-center rounded-lg border border-dashed border-medha-border bg-white px-6 py-12 text-center">
                <span
                  aria-hidden
                  className="flex h-11 w-11 items-center justify-center rounded-lg bg-medha-surface-muted text-medha-secondary"
                >
                  <Search className="h-5 w-5" />
                </span>
                <p className="mt-3 text-[15px] font-semibold text-medha-text">
                  No matching projects
                </p>
                <p className="mt-1 max-w-md text-sm leading-relaxed text-medha-secondary">
                  The current search or filters produced no matches. Try a different
                  term or clear the filters.
                </p>
                <button
                  type="button"
                  onClick={clearAll}
                  className="mt-4 rounded-lg border border-medha-border bg-white px-4 py-2 text-sm font-semibold text-medha-secondary hover:bg-medha-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
                >
                  Clear search and filters
                </button>
              </div>
            ) : (
              <div
                aria-label="Projects"
                className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
              >
                {visible.map((p) => (
                  <ProjectCard key={p.id} project={p} actions={actions} />
                ))}
              </div>
            )}
          </div>
        </div>
        {connecting ? (
          <ConnectRepoDialog onClose={() => setConnecting(false)} onDone={() => void refresh()} />
        ) : null}
        {confirm ? (
          <Dialog
            title={confirm.kind === "disconnect" ? "Disconnect repository?" : "Delete project?"}
            danger={confirm.kind === "delete"}
            confirmLabel={
              acting
                ? confirm.kind === "disconnect" ? "Disconnecting…" : "Deleting…"
                : confirm.kind === "disconnect" ? "Disconnect" : "Delete project"
            }
            confirmDisabled={acting != null}
            onConfirm={() => void confirmAction()}
            onCancel={() => setConfirm(null)}
            body={
              <div className="space-y-2">
                <p>
                  {confirm.kind === "disconnect" ? (
                    <>
                      Disconnect <span className="font-semibold text-medha-text">{confirm.project.name}</span>? Recorded runs stay inspectable, but new pushes stop routing here and analyses can no longer start until it is reconnected.
                    </>
                  ) : (
                    <>
                      Delete <span className="font-semibold text-medha-text">{confirm.project.name}</span> from this workspace? Recorded run history is preserved in the backend, but the connection mapping is removed.
                    </>
                  )}
                </p>
                {confirm.kind === "delete" && confirm.project.latest != null && isRunningStatus(confirm.project.latest.status) ? (
                  <p role="note" className="rounded-lg border border-medha-warning/30 bg-medha-warning-soft px-3 py-2 text-[13px] text-medha-warning">
                    A run is currently in flight — deletion will be refused until it finishes. Disconnect instead, or wait and retry.
                  </p>
                ) : null}
              </div>
            }
          />
        ) : null}
      </div>
    </AppShell>
  );
}