"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowRight, FolderKanban, Plus, RefreshCw, Search } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ActionLink, Badge, Button, Dialog, EmptyState, ErrorBox } from "@/components/ui/primitives";
import { ConnectRepoDialog } from "@/components/workspace/ConnectRepoDialog";
import {
  filterProjects,
  formatActivity,
  projectHealth,
  useProjects,
  type ProjectSummary,
  type ProjectStatusFilter,
} from "@/lib/projects/projects";
import { cn } from "@/lib/ui/cn";

const FILTERS: { id: string; label: string }[] = [
  { id: "all", label: "All" },
  { id: "attention", label: "Needs attention" },
  { id: "running", label: "Running" },
  { id: "healthy", label: "Healthy" },
  { id: "demo", label: "Demo only" },
  { id: "real", label: "Real runs" },
];

function healthBadge(p: ProjectSummary) {
  const health = projectHealth(p);
  const latest = p.latest?.status ?? "no runs";
  switch (health) {
    case "running":
      return <Badge tone="info">Running · {latest}</Badge>;
    case "attention":
      return <Badge tone="error">Needs attention</Badge>;
    case "healthy":
      return <Badge tone="success">Healthy</Badge>;
    default:
      return <Badge tone="neutral">{latest}</Badge>;
  }
}

function CreateDialog({ createProject, onClose, onCreated }: {
  createProject: (input: { repositoryUrl: string; mode?: string; intent?: string }) => Promise<string>;
  onClose: () => void;
  onCreated: (projectId: string) => void;
}) {
  const [repoUrl, setRepoUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function confirm() {
    if (repoUrl.trim().length < 4) {
      setError("Repository URL must be at least 4 characters (URL or local path).");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createProject({
        repositoryUrl: repoUrl,
        mode: "demo",
        intent: undefined,
      });
      onCreated(projectIdForRepo(repoUrl.trim()));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the first run for this project.");
      setSaving(false);
    }
  }

  return (
    <Dialog
      title="New project"
      confirmLabel={saving ? "Creating…" : "Create project"}
      confirmDisabled={saving}
      onConfirm={() => void confirm()}
      onCancel={onClose}
      body={
        <div className="space-y-3">
          <div>
            <label htmlFor="np-repo" className="medha-label">Repository URL or local path</label>
            <input id="np-repo" className="field-input mt-1" value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} placeholder="https://github.com/example/app or C:/src/app" />
          </div>
          {error ? <p role="alert" className="rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-[13px] text-medha-danger">{error}</p> : null}
        </div>
      }
    />
  );
}

function projectIdForRepo(repoUrl: string): string {
  return "proj_" + btoa(repoUrl).replace(/[^a-zA-Z0-9]/g, "_").substring(0, 16);
}

export function ProjectHub() {
  const { projects, total, loading, error, backendReachable, refresh, createProject } = useProjects();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<ProjectStatusFilter>("all");
  const [creating, setCreating] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [justCreated, setJustCreated] = useState<string | null>(null);

  const filtered = useMemo(() => filterProjects(projects, query, filter), [projects, query, filter]);
  const attentionCount = useMemo(() => projects.filter((p) => projectHealth(p) === "attention").length, [projects]);

  return (
    <AppShell>
      <div className="space-y-5">
        <div className="flex items-center justify-between gap-3">
          <h1 className="medha-label text-sm uppercase tracking-[0.1em] text-medha-secondary">Projects</h1>

          <Button
            variant="primary"
            onClick={() => setCreating(true)}
            className="min-w-[140px]"
          >
            <Plus className="h-4 w-4" aria-hidden /> New project
          </Button>
        </div>

        {justCreated ? (
          <p role="status" className="rounded-md border border-medha-success/30 bg-medha-success-soft px-4 py-2.5 text-sm text-medha-success">
            Project created — appears below once the backend records it.
          </p>
        ) : null}

        {!backendReachable && !loading ? (
          <ErrorBox message={error ?? "Cannot reach MEDHA backend."} onRetry={() => void refresh()} />
        ) : null}

        <div className="flex flex-col">
          <div className="relative flex items-center gap-2">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-medha-tertiary" aria-hidden />
            <label htmlFor="hub-search" className="sr-only">Search projects</label>
            <input
              id="hub-search"
              className="field-input pl-9 w-full"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name or repository…"
            />
          </div>
          <div role="group" aria-label="Status filter" className="flex flex-wrap items-center gap-2">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setFilter(f.id as ProjectStatusFilter)}
                aria-pressed={filter === f.id}
                className={cn(
                  "rounded-md px-3 py-1.5 text-[12px] font-medium transition capitalize",
                  filter === f.id
                    ? "bg-medha-surface-raised text-medha-accent"
                    : "border border-medha-border bg-medha-surface-raised text-medha-secondary hover:text-medha-text",
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" aria-label="Loading projects">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="rounded-md border border-medha-border bg-medha-surface p-4 flex items-center justify-center h-44" />
            ))}
          </div>
        ) : projects.length === 0 && backendReachable ? (
          <EmptyState
            title="No projects yet"
            body="Create a project to start its first backend run — a simulated demo scenario or the real local pipeline. Projects appear here once the API records a run."
            action={<Button variant="primary" onClick={() => setCreating(true)}><Plus className="h-4 w-4" aria-hidden /> New project</Button>}
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            title="No matches"
            body="Try a different search term or status filter."
          />
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-3" aria-label="Projects">
            {filtered.map((p) => (
              <div
                key={p.id}
                tabIndex={0}
                role="button"
                aria-label={`Open ${p.name} project`}
                onClick={() => window.location.href = `/projects/${p.id}`}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    window.location.href = `/projects/${p.id}`;
                  }
                }}
                className={cn(
                  "rounded-md border border-medha-border bg-medha-surface p-4 flex flex-col h-full transition-colors hover:bg-medha-surface-raised focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent",
                  projectHealth(p) === "attention" && "border-medha-danger/25",
                  "focus-visible-outline",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-2">
                    <span className="mt-0.5 rounded-lg bg-medha-accent-soft p-1.5 text-medha-accent" aria-hidden>
                      <FolderKanban className="h-3.5 w-3.5" />
                    </span>
                    <div className="min-w-0">
                      <h2 className="truncate text-[14px] font-semibold text-medha-text">{p.name}</h2>
                      <p className="medha-mono mt-0.5 truncate text-[11px] text-medha-tertiary">{p.repositoryUrl}</p>
                    </div>
                  </div>
                  {healthBadge(p)}
                </div>
                <div className="mt-3 text-[12px] text-medha-secondary flex-1">
                  <div className="flex gap-2 mb-1">
                    <span>·</span>
                    <span>{formatActivity(p.lastActivity)}</span>
                  </div>
                  <div className="flex gap-2">
                    <span className="text-medha-tertiary">Runs</span>
                    <span>{p.totalRuns} total{p.demoRuns > 0 ? ` · ${p.demoRuns} demo` : ""}{p.realRuns > 0 ? ` · ${p.realRuns} real` : ""}</span>
                  </div>
                </div>
                <div className="mt-3 flex items-center justify-between">
                  <Link
                    href={`/projects/${p.id}`}
                    className="inline-flex items-center gap-1 text-sm font-semibold text-medha-primary hover:underline"
                  >
                    Open project <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}

        <section className="mt-4 rounded-md border border-medha-border bg-medha-surface p-4 text-[11px] leading-relaxed text-medha-secondary" aria-label="About hub data">
          <p>
            Project health, run counts, and attention items are computed from backend runs.
            Start a fresh analysis any time from the New analysis page.
          </p>
        </section>
      </div>
      {creating ? (
        <CreateDialog
          createProject={createProject as (input: { repositoryUrl: string; mode?: string; intent?: string }) => Promise<string>}
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setJustCreated(id);
            void refresh();
          }}
        />
      ) : null}
      {connecting ? (
        <ConnectRepoDialog
          onClose={() => setConnecting(false)}
          onDone={() => void refresh()}
        />
      ) : null}
    </AppShell>
  );
}

export function HubActions() {
  return <ActionLink href="/verify" primary>Start verification</ActionLink>;
}