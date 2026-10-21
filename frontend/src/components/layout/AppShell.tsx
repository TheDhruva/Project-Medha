"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import {
  ArrowLeft, FolderKanban, GitBranch, LayoutDashboard, Menu, PlayCircle,
  Rocket, Settings, X,
} from "lucide-react";
import { Header } from "@/components/layout/Header";
import {
  canonicalRepoKey,
  repoForProjectId,
  shortNameForRepo,
  useProjects,
} from "@/lib/projects/projects";
import { cn } from "@/lib/ui/cn";

function projectHref(projectId: string, suffix = "") {
  return `/projects/${projectId}${suffix}`;
}

function normalizePath(pathname: string): string {
  const trimmed = pathname.replace(/\/+$/, "");
  return trimmed || "/";
}

function isPathOrChild(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/* Workspace-wide destinations. `/runs` lists runs across all projects and
   `/settings` configures the local product — both distinct from the
   project-scoped destinations below, so both navigations are retained. */
const WORKSPACE_ITEMS = [
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/runs", label: "All runs", icon: PlayCircle },
  { href: "/settings", label: "Workspace settings", icon: Settings },
];

function workspaceActive(pathname: string, href: string): boolean {
  if (href === "/projects") return pathname === "/projects";
  return isPathOrChild(pathname, href);
}

function projectRepo(summary: {
  repoOwner: string | null;
  repoName: string | null;
  repositoryUrl: string;
}): string | null {
  if (summary.repoOwner && summary.repoName) {
    return `${summary.repoOwner}/${summary.repoName}`;
  }
  return canonicalRepoKey(summary.repositoryUrl) ?? summary.repositoryUrl ?? null;
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = normalizePath(usePathname() ?? "");
  const params = useParams<{ id?: string }>();
  const { projects, loading } = useProjects();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const activeId = params?.id ?? null;
  const inProject =
    Boolean(activeId) && pathname.startsWith("/projects/") && pathname !== "/projects";
  const activeProject = inProject
    ? projects.find((project) => project.id === activeId) ?? null
    : null;
  const legacyRepo =
    inProject && activeId && !activeProject && !activeId.startsWith("prj_")
      ? repoForProjectId(activeId)
      : null;
  const identityName = activeProject?.name ?? (legacyRepo ? shortNameForRepo(legacyRepo) : null);
  const identityRepo = activeProject
    ? projectRepo(activeProject)
    : legacyRepo
      ? canonicalRepoKey(legacyRepo) ?? legacyRepo
      : null;
  const identityPending = inProject && !identityName && loading;

  // The drawer is route chrome: close it on navigation and on Escape.
  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileNavOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileNavOpen]);

  const projectBase = activeId ? projectHref(activeId) : "";
  const runDetailPrefix = `${projectBase}/runs/`;
  const deploymentsHref =
    inProject && pathname.startsWith(runDetailPrefix)
      ? pathname
      : activeProject?.latest
        ? `${projectBase}/runs/${activeProject.latest.deployment_id}`
        : `${projectBase}/runs`;
  const projectItems = activeId
    ? [
        {
          href: projectBase,
          label: "Overview",
          icon: LayoutDashboard,
          active: pathname === projectBase,
        },
        {
          href: `${projectBase}/runs`,
          label: "Runs",
          icon: PlayCircle,
          active: pathname === `${projectBase}/runs`,
        },
        {
          href: `${projectBase}/graphs`,
          label: "Architecture",
          icon: GitBranch,
          active: isPathOrChild(pathname, `${projectBase}/graphs`),
        },
        {
          href: deploymentsHref,
          label: "Deployments",
          icon: Rocket,
          active: pathname.startsWith(runDetailPrefix),
        },
        {
          href: `${projectBase}/settings`,
          label: "Settings",
          icon: Settings,
          active: isPathOrChild(pathname, `${projectBase}/settings`),
        },
      ]
    : [];
  const workspaceItems = inProject
    ? WORKSPACE_ITEMS.filter((item) => item.href !== "/projects")
    : WORKSPACE_ITEMS;

  const nav = (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      {inProject ? (
        <div className="mb-3 border-b border-medha-border pb-3">
          <Link
            href="/projects"
            aria-label="All projects"
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[13px] font-medium text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
          >
            <ArrowLeft className="h-3.5 w-3.5 shrink-0" aria-hidden />
            All projects
          </Link>
          <div className="mt-1 min-w-0 px-2">
            <p
              className={cn(
                "truncate text-[14.5px] font-semibold leading-5 text-medha-text",
                identityPending && "text-medha-secondary",
              )}
              title={identityName ?? undefined}
            >
              {identityName ?? (identityPending ? "Loading project…" : "Project unavailable")}
            </p>
            {identityRepo ? (
              <p
                className="medha-mono truncate text-[12px] leading-4 text-medha-tertiary"
                title={identityRepo}
              >
                {identityRepo}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}

      {inProject ? (
        <nav aria-label="Project" className="shrink-0">
          <p className="medha-label px-2.5">Project</p>
          <ul className="mt-1 space-y-0.5">
            {projectItems.map((item) => (
              <li key={item.label}>
                <Link
                  href={item.href}
                  aria-current={item.active ? "page" : undefined}
                  className={cn(
                    "sidebar-nav-link",
                    item.active && "sidebar-nav-link-active",
                  )}
                >
                  <item.icon className="h-4 w-4 shrink-0" aria-hidden />
                  <span className="truncate">{item.label}</span>
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}

      <nav
        aria-label="Workspace"
        className={cn(
          "shrink-0",
          inProject && "mt-4 border-t border-medha-border pt-3",
        )}
      >
        <p className="medha-label px-2.5">Workspace</p>
        <ul className="mt-1 space-y-0.5">
          {workspaceItems.map((item) => {
            const isActive = !inProject && workspaceActive(pathname, item.href);
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={isActive ? "page" : undefined}
                  className={cn(
                    "sidebar-nav-link",
                    isActive && "sidebar-nav-link-active",
                  )}
                >
                  <item.icon className="h-4 w-4 shrink-0" aria-hidden />
                  <span className="truncate">{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );

  return (
    <div className="min-h-screen bg-medha-bg text-medha-text">
      <Header />
      <div className="mx-auto flex w-full max-w-[1600px] items-start">
        <aside
          id="workspace-navigation"
          aria-label="Workspace navigation"
          className={cn(
            "shrink-0 border-r border-medha-border bg-medha-sidebar p-3",
            "md:sticky md:top-16 md:flex md:h-[calc(100svh-4rem)] md:w-60 md:flex-col",
            mobileNavOpen
              ? "fixed inset-y-0 left-0 top-16 z-40 flex w-72 max-w-[85vw] flex-col shadow-medha"
              : "hidden",
          )}
        >
          {mobileNavOpen ? (
            <button
              type="button"
              onClick={() => setMobileNavOpen(false)}
              aria-label="Close navigation"
              className="absolute right-2 top-2 inline-flex h-8 w-8 items-center justify-center rounded-md text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent md:hidden"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          ) : null}
          {nav}
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <main className="w-full min-w-0 flex-1 p-4 sm:p-6 lg:p-8">
            {!mobileNavOpen ? (
              <button
                type="button"
                className="medha-button medha-secondary mb-4 md:hidden"
                onClick={() => setMobileNavOpen(true)}
                aria-expanded="false"
                aria-controls="workspace-navigation"
              >
                <Menu className="h-4 w-4" aria-hidden />
                Open navigation
              </button>
            ) : null}
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
