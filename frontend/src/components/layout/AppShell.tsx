"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import {
  FolderKanban, LayoutDashboard, PlayCircle,
  Settings, Menu, X,
} from "lucide-react";
import { Header } from "@/components/layout/Header";
import { repoForProjectId, useProjects } from "@/lib/projects/projects";
import { cn } from "@/lib/ui/cn";

function projectHref(projectId: string, suffix = "") {
  return `/projects/${projectId}${suffix}`;
}

/* Workspace-wide destinations. `/runs` lists runs across all projects and
   `/settings` configures the local product — both distinct from the
   project-scoped destinations below, so both navigations are retained. */
const WORKSPACE_ITEMS = [
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/runs", label: "All runs", icon: PlayCircle },
  { href: "/settings", label: "Workspace settings", icon: Settings },
];

function isWorkspaceActive(pathname: string, href: string): boolean {
  if (href === "/projects") return pathname === "/projects";
  if (href === "/runs") return pathname === "/runs" || pathname.startsWith("/runs/");
  return pathname === href || pathname.startsWith(`${href}/`);
}

function isProjectActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  const params = useParams<{ id?: string }>();
  const router = useRouter();
  const { projects } = useProjects();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const activeId = params?.id ?? null;
  const inProject = pathname.startsWith("/projects/") && activeId;
  const active = projects.find((p) => p.id === activeId) ?? null;
  const fallbackRepo = activeId ? repoForProjectId(activeId) : null;
  const activeRepo = active?.repositoryUrl ?? fallbackRepo;

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

  const projectItems = activeId
    ? [
        { href: projectHref(activeId), label: "Project overview", icon: LayoutDashboard },
        { href: projectHref(activeId, "/runs"), label: "Project runs", icon: PlayCircle },
        { href: projectHref(activeId, "/settings"), label: "Project settings", icon: Settings },
      ]
    : [];

  const nav = (
    <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto">
      <nav aria-label="Workspace" className="shrink-0">
        <p className="medha-label px-2">Workspace</p>
        <ul className="mt-1.5 space-y-1">
          {WORKSPACE_ITEMS.map((item) => {
            const isActive = !inProject && isWorkspaceActive(pathname, item.href);
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
                  <span>{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <nav aria-label="Current project" className="min-w-0 shrink-0">
        <p className="medha-label px-2">Current project</p>
        <div className="mt-1.5 px-0">
          <label htmlFor="appshell-project" className="sr-only">Active project</label>
          <select
            id="appshell-project"
            value={activeId ?? ""}
            onChange={(e) => {
              const id = e.target.value;
              if (id) router.push(projectHref(id));
            }}
            className="field-input w-full py-2"
          >
            <option value="">Select a project…</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          {activeRepo ? (
            <p title={activeRepo} className="medha-mono mt-1.5 truncate px-2 text-[12px] text-medha-secondary">
              {activeRepo}
            </p>
          ) : null}
        </div>
        {activeId ? (
          <ul className="mt-1.5 space-y-1">
            {projectItems.map((item) => {
              const isActive = inProject && isProjectActive(pathname, item.href);
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
                    <span>{item.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : null}
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
            "shrink-0 border-r border-medha-border bg-medha-sidebar p-4",
            "md:sticky md:top-16 md:flex md:h-[calc(100svh-4rem)] md:w-60 md:flex-col",
            mobileNavOpen
              ? "fixed inset-y-0 left-0 top-16 z-40 flex w-72 max-w-[85vw] flex-col shadow-medha"
              : "hidden",
          )}
        >
          {nav}
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <main className="w-full min-w-0 flex-1 p-4 sm:p-6 lg:p-8">
            <button
              type="button"
              className="medha-button medha-secondary mb-4 md:hidden"
              onClick={() => setMobileNavOpen((open) => !open)}
              aria-expanded={mobileNavOpen}
              aria-controls="workspace-navigation"
            >
              {mobileNavOpen ? <X className="h-4 w-4" aria-hidden /> : <Menu className="h-4 w-4" aria-hidden />}
              {mobileNavOpen ? "Close navigation" : "Open navigation"}
            </button>
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
