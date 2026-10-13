"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  Copy,
  Filter,
  FolderKanban,
  MoreHorizontal,
  Plus,
  Search,
  X,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ConnectRepoDialog } from "@/components/workspace/ConnectRepoDialog";
import {
  PROJECT_CARD_STATUS_META,
  filterProjectsByStatus,
  formatActivity,
  projectCardStatus,
  sortProjects,
  useProjects,
  type ProjectCardStatus,
  type ProjectSort,
  type ProjectSummary,
} from "@/lib/projects/projects";

/* Palette (matches landing tokens): bg #F8FAFC, surface #FFFFFF,
   text #111827, secondary #64748B, accent #2563EB, success #059669,
   borders #E2E8F0. Amber/red variants use dark-on-tint pairs for AA. */

const SORT_OPTIONS: { id: ProjectSort; label: string }[] = [
  { id: "recent", label: "Recently active" },
  { id: "name", label: "Name" },
  { id: "status", label: "Status" },
];

function StatusBadge({ status }: { status: ProjectCardStatus }) {
  const base =
    "inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold whitespace-nowrap";
  switch (status) {
    case "attention":
      return (
        <span className={`${base} border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C]`}>
          <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#DC2626]" />
          Needs attention
        </span>
      );
    case "running":
      return (
        <span className={`${base} border-[#BFDBFE] bg-[#EFF6FF] text-[#1D4ED8]`}>
          <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#2563EB]" />
          Running
        </span>
      );
    case "completed":
      // Neutral slate — a finished run reports completion only, never health.
      return (
        <span className={`${base} border-[#E2E8F0] bg-[#F1F5F9] text-[#334155]`}>
          <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#64748B]" />
          Completed
        </span>
      );
    default:
      return (
        <span className={`${base} border-[#E2E8F0] bg-white text-[#64748B]`}>
          <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#CBD5E1]" />
          No runs yet
        </span>
      );
  }
}

function CardMenu({ project }: { project: ProjectSummary }) {
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
  }, [open ]);

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
    "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] text-[#334155] hover:bg-[#F1F5F9] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#2563EB]";

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
        className="rounded-md p-1.5 text-[#64748B] hover:bg-[#F1F5F9] hover:text-[#111827] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563EB]"
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label={`Actions for ${project.name}`}
          className="absolute right-0 top-full z-30 mt-1 w-48 rounded-lg border border-[#E2E8F0] bg-white p-1 shadow-[0_8px_24px_rgba(17,24,39,0.12)]"
          onClick={(e) => e.stopPropagation()}
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
          <Link
            role="menuitem"
            href={`/projects/${project.id}/settings`}
            className={itemCls}
            onClick={() => setOpen(false)}
          >
            Project settings
          </Link>
          <button type="button" role="menuitem" className={itemCls} onClick={() => void copyUrl()}>
            {copied ? (
              <Check className="h-3.5 w-3.5 text-[#059669]" aria-hidden />
            ) : (
              <Copy className="h-3.5 w-3.5" aria-hidden />
            )}
            {copied ? "Copied URL" : "Copy repository URL"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function ProjectCard({ project }: { project: ProjectSummary }) {
  const status = projectCardStatus(project);
  const latest = project.latest;
  const activity = latest
    ? `${latest.status.replace(/_/g, " ")} · ${formatActivity(project.lastActivity)}`
    : "No runs yet";

  return (
    <article
      aria-label={project.name}
      className="flex h-full flex-col rounded-lg border border-[#E2E8F0] bg-white p-4 shadow-[0_1px_2px_rgba(17,24,39,0.06)] transition-shadow hover:shadow-[0_4px_16px_rgba(17,24,39,0.08)] sm:aspect-square"
    >
      <div className="flex items-start justify-between gap-2">
        <span
          aria-hidden
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-[#EFF6FF] text-[#2563EB]"
        >
          <FolderKanban className="h-4 w-4" />
        </span>
        <CardMenu project={project} />
      </div>

      <div className="mt-3 min-w-0">
        <h2
          title={project.name}
          className="break-words text-[15px] font-semibold leading-snug tracking-tight text-[#111827] line-clamp-2"
        >
          {project.name}
        </h2>
        <p
          title={project.repositoryUrl}
          className="mt-0.5 truncate font-mono text-[11.5px] text-[#64748B]"
        >
          {project.repositoryUrl}
        </p>
      </div>

      <div className="mt-2.5">
        <StatusBadge status={status} />
      </div>

      <p className="mt-2 min-w-0 truncate text-[12.5px] text-[#64748B]" title={activity}>
        {activity}
      </p>
      {project.totalRuns > 0 ? (
        <p className="mt-0.5 text-[12px] text-[#94A3B8]">
          {project.totalRuns} run{project.totalRuns === 1 ? "" : "s"}
          {project.latest?.is_demo ? " · DEMO" : ""}
        </p>
      ) : null}

      <div className="mt-auto pt-3">
        <Link
          href={`/projects/${project.id}`}
          aria-label={`Open ${project.name} project`}
          className="inline-flex items-center gap-1 rounded-md text-[13.5px] font-semibold text-[#2563EB] hover:text-[#1D4ED8] hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563EB]"
        >
          Open project <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </Link>
      </div>
    </article>
  );
}

function SkeletonGrid() {
  return (
    <div
      aria-label="Loading projects"
      role="status"
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
    >
      {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
        <div
          key={i}
          className="rounded-lg border border-[#E2E8F0] bg-white p-4 sm:aspect-square"
        >
          <div className="flex items-start justify-between">
            <div className="h-8 w-8 rounded-md bg-[#F1F5F9]" />
            <div className="h-6 w-6 rounded-md bg-[#F1F5F9]" />
          </div>
          <div className="mt-3 h-4 w-3/4 rounded bg-[#F1F5F9]" />
          <div className="mt-2 h-3 w-full rounded bg-[#F1F5F9]" />
          <div className="mt-3 h-5 w-24 rounded-full bg-[#F1F5F9]" />
          <div className="mt-auto pt-3">
            <div className="h-4 w-28 rounded bg-[#F1F5F9]" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ProjectHub() {
  const { projects, loading, error, backendReachable, refresh } = useProjects();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<ProjectCardStatus[]>([]);
  const [sort, setSort] = useState<ProjectSort>("recent");
  const [filterOpen, setFilterOpen] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const filterWrapRef = useRef<HTMLDivElement>(null);
  const filterButtonRef = useRef<HTMLButtonElement>(null);

  const activeSet = useMemo(() => new Set(active), [active]);

  const visible = useMemo(
    () => sortProjects(filterProjectsByStatus(projects, query, activeSet), sort),
    [projects, query, activeSet, sort],
  );

  const counts = useMemo(() => {
    let attention = 0;
    let noRuns = 0;
    for (const p of projects) {
      const s = projectCardStatus(p);
      if (s === "attention") attention += 1;
      if (s === "no_runs") noRuns += 1;
    }
    return { total: projects.length, attention, noRuns };
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

  function toggleStatus(id: ProjectCardStatus) {
    setActive((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]));
  }

  function clearAll() {
    setQuery("");
    setActive([]);
  }

  const failed = !!error && !backendReachable && !loading;
  const hasCache = projects.length > 0;
  const showSkeletons = loading && !hasCache;

  return (
    <AppShell>
      {/* Full-bleed bright workspace inside AppShell's padded main. */}
      <div className="-m-4 min-h-[calc(100svh-64px)] bg-[#F8FAFC] p-4 sm:-m-6 sm:p-6 lg:-m-8 lg:p-8">
        <div className="mx-auto w-full max-w-[1400px]">
          {/* Header */}
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="text-[24px] font-bold leading-tight tracking-tight text-[#111827]">
                Projects
              </h1>
              <p className="mt-1 max-w-2xl text-[13.5px] leading-relaxed text-[#64748B]">
                Manage your connected repositories and inspect their latest runs.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setConnecting(true)}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-semibold text-white shadow-[0_1px_2px_rgba(37,99,235,0.4)] transition hover:bg-[#1D4ED8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563EB]"
            >
              <Plus className="h-4 w-4" aria-hidden /> New project
            </button>
          </div>

          {/* Compact summary (truthful counts from the same dataset) */}
          {!loading && !failed ? (
            <p className="mt-3 text-[12.5px] text-[#64748B]" role="status">
              {counts.total} project{counts.total === 1 ? "" : "s"}
              {" · "}
              {counts.attention} needing attention
              {" · "}
              {counts.noRuns} with no runs
              {query.trim() || active.length > 0 ? (
                <span>
                  {" · "}showing {visible.length} of {counts.total}
                </span>
              ) : null}
            </p>
          ) : null}

          {/* Toolbar */}
          <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#94A3B8]"
                aria-hidden
              />
              <label htmlFor="projects-search" className="sr-only">
                Search repositories
              </label>
              <input
                id="projects-search"
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search repositories..."
                autoComplete="off"
                className="w-full rounded-lg border border-[#E2E8F0] bg-white py-2 pl-9 pr-8 text-sm text-[#111827] shadow-[0_1px_2px_rgba(17,24,39,0.05)] placeholder:text-[#94A3B8] focus:border-[#2563EB] focus:outline-none focus:ring-2 focus:ring-[#2563EB]/25"
              />
              {query ? (
                <button
                  type="button"
                  aria-label="Clear search"
                  onClick={() => setQuery("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-[#64748B] hover:bg-[#F1F5F9] hover:text-[#111827] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#2563EB]"
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
                  className={`inline-flex items-center gap-1.5 rounded-lg border px-3.5 py-2 text-sm font-medium transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563EB] ${
                    active.length > 0
                      ? "border-[#2563EB] bg-[#EFF6FF] text-[#1D4ED8]"
                      : "border-[#E2E8F0] bg-white text-[#334155] hover:bg-[#F1F5F9]"
                  }`}
                >
                  <Filter className="h-4 w-4" aria-hidden />
                  Filter
                  {active.length > 0 ? (
                    <span
                      aria-label={`${active.length} status filters active`}
                      className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-[#2563EB] px-1.5 text-[11px] font-bold text-white"
                    >
                      {active.length}
                    </span>
                  ) : null}
                </button>

                {filterOpen ? (
                  <div
                    id="projects-filter-popover"
                    role="dialog"
                    aria-label="Filter and sort projects"
                    className="absolute left-0 top-full z-40 mt-2 max-w-[calc(100vw-2rem)] rounded-lg border border-[#E2E8F0] bg-white p-4 shadow-[0_8px_24px_rgba(17,24,39,0.12)]"
                  >
                    <fieldset>
                      <legend className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[#64748B]">
                        Status
                      </legend>
                      <div className="mt-2 space-y-1.5">
                        {PROJECT_CARD_STATUS_META.map((s) => (
                          <label
                            key={s.id}
                            className="flex cursor-pointer items-center gap-2.5 rounded-md px-1.5 py-1.5 text-[13.5px] text-[#334155] hover:bg-[#F8FAFC] focus-within:outline focus-within:outline-2 focus-within:outline-[#2563EB]"
                          >
                            <input
                              type="checkbox"
                              checked={active.includes(s.id)}
                              onChange={() => toggleStatus(s.id)}
                              className="h-4 w-4 shrink-0 rounded border-[#CBD5E1] accent-[#2563EB]"
                            />
                            {s.label}
                          </label>
                        ))}
                      </div>
                    </fieldset>

                    <fieldset className="mt-3 border-t border-[#E2E8F0] pt-3">
                      <legend className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[#64748B]">
                        Sort by
                      </legend>
                      <div className="mt-2 space-y-1.5">
                        {SORT_OPTIONS.map((o) => (
                          <label
                            key={o.id}
                            className="flex cursor-pointer items-center gap-2.5 rounded-md px-1.5 py-1.5 text-[13.5px] text-[#334155] hover:bg-[#F8FAFC] focus-within:outline focus-within:outline-2 focus-within:outline-[#2563EB]"
                          >
                            <input
                              type="radio"
                              name="projects-sort"
                              checked={sort === o.id}
                              onChange={() => setSort(o.id)}
                              className="h-4 w-4 shrink-0 border-[#CBD5E1] accent-[#2563EB]"
                            />
                            {o.label}
                          </label>
                        ))}
                      </div>
                    </fieldset>

                    <div className="mt-3 flex items-center justify-between border-t border-[#E2E8F0] pt-3">
                      <button
                        type="button"
                        onClick={() => {
                          setActive([]);
                          setSort("recent");
                        }}
                        disabled={active.length === 0 && sort === "recent"}
                        className="rounded-md px-2 py-1 text-[13px] font-medium text-[#64748B] hover:bg-[#F1F5F9] hover:text-[#111827] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#2563EB]"
                      >
                        Reset
                      </button>
                      <button
                        type="button"
                        onClick={() => setFilterOpen(false)}
                        className="rounded-md bg-[#2563EB] px-3 py-1.5 text-[13px] font-semibold text-white hover:bg-[#1D4ED8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563EB]"
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
                className="max-w-[160px] truncate rounded-lg border border-[#E2E8F0] bg-white px-3 py-2 text-sm text-[#334155] focus:border-[#2563EB] focus:outline-none focus:ring-2 focus:ring-[#2563EB]/25"
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
              className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#FECACA] bg-[#FEF2F2] px-3 py-2 text-[13px]"
            >
              <p className="min-w-0 flex-1 text-[#991B1B]">
                <span className="font-semibold">Couldn&apos;t refresh projects. </span>
                <span className="break-words">{error ?? "The backend is unreachable."}</span>
                {hasCache ? <span> Showing last known projects.</span> : null}
              </p>
              <button
                type="button"
                onClick={() => void refresh()}
                className="shrink-0 rounded-md border border-[#FECACA] bg-white px-3 py-1.5 text-[12.5px] font-semibold text-[#B91C1C] hover:bg-[#FEF2F2] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563EB]"
              >
                Retry
              </button>
            </div>
          ) : null}

          {/* Content */}
          <div className="mt-4">
            {showSkeletons ? (
              <SkeletonGrid />
            ) : failed && !hasCache ? (
              <div className="flex flex-col items-center rounded-lg border border-[#E2E8F0] bg-white px-6 py-12 text-center">
                <span
                  aria-hidden
                  className="flex h-11 w-11 items-center justify-center rounded-lg bg-[#F1F5F9] text-[#64748B]"
                >
                  <FolderKanban className="h-5 w-5" />
                </span>
                <p className="mt-3 text-[15px] font-semibold text-[#111827]">
                  Projects couldn&apos;t load
                </p>
                <p className="mt-1 max-w-md text-sm leading-relaxed text-[#64748B]">
                  The request failed before any project data arrived. Check that the
                  backend is running, then try again.
                </p>
                <button
                  type="button"
                  onClick={() => void refresh()}
                  className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-semibold text-white hover:bg-[#1D4ED8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563EB]"
                >
                  Retry
                </button>
              </div>
            ) : counts.total === 0 ? (
              <div className="flex flex-col items-center rounded-lg border border-[#E2E8F0] bg-white px-6 py-12 text-center">
                <span
                  aria-hidden
                  className="flex h-11 w-11 items-center justify-center rounded-lg bg-[#EFF6FF] text-[#2563EB]"
                >
                  <FolderKanban className="h-5 w-5" />
                </span>
                <p className="mt-3 text-[15px] font-semibold text-[#111827]">No projects yet</p>
                <p className="mt-1 max-w-md text-sm leading-relaxed text-[#64748B]">
                  Connect a repository to record its first analysis. Projects appear
                  here once the backend records a run for them.
                </p>
                <button
                  type="button"
                  onClick={() => setConnecting(true)}
                  className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-semibold text-white hover:bg-[#1D4ED8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563EB]"
                >
                  <Plus className="h-4 w-4" aria-hidden /> New project
                </button>
              </div>
            ) : visible.length === 0 ? (
              <div className="flex flex-col items-center rounded-lg border border-dashed border-[#E2E8F0] bg-white px-6 py-12 text-center">
                <span
                  aria-hidden
                  className="flex h-11 w-11 items-center justify-center rounded-lg bg-[#F1F5F9] text-[#64748B]"
                >
                  <Search className="h-5 w-5" />
                </span>
                <p className="mt-3 text-[15px] font-semibold text-[#111827]">
                  No matching projects
                </p>
                <p className="mt-1 max-w-md text-sm leading-relaxed text-[#64748B]">
                  The current search or filters produced no matches. Try a different
                  term or clear the filters.
                </p>
                <button
                  type="button"
                  onClick={clearAll}
                  className="mt-4 rounded-lg border border-[#E2E8F0] bg-white px-4 py-2 text-sm font-semibold text-[#334155] hover:bg-[#F1F5F9] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563EB]"
                >
                  Clear search and filters
                </button>
              </div>
            ) : (
              <div
                aria-label="Projects"
                className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
              >
                {visible.map((p) => (
                  <ProjectCard key={p.id} project={p} />
                ))}
              </div>
            )}
          </div>

          <p className="mt-5 border-t border-[#E2E8F0] pt-3 text-[12px] leading-relaxed text-[#94A3B8]">
            Project status reflects recorded backend runs only. A finished run is
            reported as completed — never as healthy without observed health-check
            evidence.
          </p>
        </div>
      </div>
      {connecting ? (
        <ConnectRepoDialog onClose={() => setConnecting(false)} onDone={() => void refresh()} />
      ) : null}
    </AppShell>
  );
}
