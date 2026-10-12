"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import {
  LayoutDashboard, Network, GitPullRequest, PlayCircle, ShieldCheck,
  FlaskConical, Settings, Menu, X, Boxes, Beaker, FileCheck, Share2,
} from "lucide-react";
import { Header } from "@/components/layout/Header";
import { repoForProjectId, shortNameForRepo, useProjects } from "@/lib/projects/projects";
import { cn } from "@/lib/ui/cn";

function projectHref(projectId: string, suffix = "") {
  return `/projects/${projectId}${suffix}`;
}

const GLOBAL_ITEMS = [
  { href: "/", label: "Project hub", icon: Boxes },
  { href: "/demo", label: "Try demo", icon: Beaker },
  { href: "/runs", label: "All runs", icon: PlayCircle },
  { href: "/proposals", label: "Proposals", icon: FileCheck },
  { href: "/verify", label: "New analysis", icon: ShieldCheck },
  { href: "/evaluation", label: "Research eval", icon: FlaskConical },
  { href: "/settings", label: "Global settings", icon: Settings },
];

function isGlobalActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  if (href === "/runs") return pathname === "/runs" || /^\/runs\/[^/]+$/.test(pathname);
  return pathname === href || pathname.startsWith(`${href}/`);
}

function isProjectActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  const params = useParams<{ id?: string }>();
  const { projects } = useProjects();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const activeId = params?.id ?? null;
  const inProject = pathname.startsWith("/projects/") && activeId;
  const active = projects.find((p) => p.id === activeId) ?? null;
  const fallbackRepo = activeId ? repoForProjectId(activeId) : null;

  const projectItems = activeId
    ? [
        { href: projectHref(activeId), label: "Overview", icon: LayoutDashboard, exact: true },
        { href: projectHref(activeId, "/orchestration"), label: "Orchestration", icon: Network },
        { href: projectHref(activeId, "/changes"), label: "Changes & Reviews", icon: GitPullRequest },
        { href: projectHref(activeId, "/runs"), label: "Runs & Executions", icon: PlayCircle },
        { href: projectHref(activeId, "/verification"), label: "Verification", icon: ShieldCheck },
        { href: projectHref(activeId, "/graphs"), label: "Graphs & Impact", icon: Share2 },
        { href: projectHref(activeId, "/evaluations"), label: "Evaluations", icon: FlaskConical },
        { href: projectHref(activeId, "/settings"), label: "Project Settings", icon: Settings },
      ]
    : [];

  const nav = (
    <nav className="flex h-full flex-col gap-2 pr-2 overflow-y-auto">
      <div>
        <p className="medha-label px-2">Project</p>
        <label htmlFor="appshell-project" className="sr-only">Active project</label>
        <select
          id="appshell-project"
          value={activeId ?? ""}
          onChange={(e) => {
            const id = e.target.value;
            if (id) window.location.href = projectHref(id);
          }}
          className="field-input mt-2 w-48"
        >
          <option value="">Select a project…</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        {active ? (
          <p className="medha-mono mt-1.5 truncate px-2 text-[12px] text-medha-secondary">{active.repositoryUrl}</p>
        ) : fallbackRepo ? (
          <p className="medha-mono mt-1.5 truncate px-2 text-[12px] text-medha-secondary">{fallbackRepo}</p>
        ) : null}
      </div>
      {inProject ? (
        <nav aria-label="Project" className="flex-1 space-y-1.5 px-2">
          {projectItems.map((item) => {
            const isActive = isProjectActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "sidebar-nav-link flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition",
                  isActive ? "sidebar-nav-link-active" : "",
                )}
              >
                <item.icon className="h-4 w-4 shrink-0" aria-hidden />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
      ) : null}
      <nav aria-label="Global" className="flex-1 space-y-1.5 px-2">
        <p className="medha-label px-2">MEDHA</p>
        {GLOBAL_ITEMS.map((item) => {
          const active = !inProject && isGlobalActive(pathname, item.href);
          return (
            <Link
              key={item.href + item.label}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "sidebar-nav-link flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition",
                active ? "sidebar-nav-link-active" : "",
              )}
            >
              <item.icon className="h-4 w-4 shrink-0" aria-hidden />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </nav>
  );

  return (
    <div className="min-h-screen bg-medha-bg">
      <Header />
      <div className="flex min-h-[calc(100svh-64px)]">
        <aside
          id="mobile-navigation"
          className={cn(
            "h-[calc(100svh-64px)] w-64 shrink-0 overflow-y-auto border-r border-medha-border bg-medha-sidebar p-4 md:sticky md:top-0 md:flex md:flex-col md:gap-2",
            mobileNavOpen ? "fixed inset-y-0 left-0 top-16 z-30 flex flex-col gap-2 shadow-medha" : "hidden",
          )}
        >
          {nav}
        </aside>
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <main className="mx-auto w-full max-w-[1600px] flex-1 overflow-x-auto p-4 sm:p-6 lg:p-8">
            <button
              type="button"
              className="medha-button medha-secondary mb-4 md:hidden"
              onClick={() => setMobileNavOpen((open) => !open)}
              aria-expanded={mobileNavOpen}
              aria-controls="mobile-navigation"
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