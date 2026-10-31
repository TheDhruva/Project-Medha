"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  ArrowRight,
  Boxes,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Container,
  FileCode2,
  FileJson2,
  Folder,
  FolderGit2,
  GitBranch,
  Hammer,
  ListChecks,
  Network,
  Server,
  Settings2,
  Shield,
} from "lucide-react";
import { AuthChoiceDialog } from "@/components/landing/AuthChoiceDialog";

// The three concerns MEDHA coordinates during a deployment (real agents).
const COMPONENTS = [
  { icon: Hammer, label: "Build" },
  { icon: Network, label: "Network" },
  { icon: Shield, label: "Security" },
];

// Verifier categories that actually exist. No status is shown: this is a
// conceptual illustration, not live analysis output.
const CHECKS = [
  { icon: Settings2, label: "Configuration" },
  { icon: Container, label: "Services" },
  { icon: Shield, label: "Security" },
  { icon: ListChecks, label: "Deployment plan" },
];

function ArrowDown({ className = "" }: { className?: string }) {
  return (
    <div className={`flex flex-col items-center justify-center ${className}`} aria-hidden>
      <span className="h-4 w-px bg-[var(--lp-connector)]" />
      <ChevronDown className="h-3.5 w-3.5 lp-tertiary" />
    </div>
  );
}

function ArrowSide({ dir, className = "" }: { dir: "left" | "right"; className?: string }) {
  return (
    <div className={`flex items-center justify-center ${className}`} aria-hidden>
      {dir === "left" ? (
        <ChevronLeft className="-mr-1 h-3.5 w-3.5 lp-tertiary" />
      ) : null}
      <span className="h-px w-5 bg-[var(--lp-connector)]" />
      {dir === "right" ? (
        <ChevronRight className="-ml-1 h-3.5 w-3.5 lp-tertiary" />
      ) : null}
    </div>
  );
}

function RepositoryPanel() {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-[10px] border lp-border lp-surface">
      <div className="flex items-center gap-2 border-b px-3.5 py-2.5 lp-border">
        <FolderGit2 className="h-3.5 w-3.5 shrink-0 lp-tertiary" aria-hidden />
        <span className="lp-mono truncate text-[11px] font-medium lp-secondary">
          repository
        </span>
      </div>

      <div className="lp-mono flex flex-1 flex-col justify-center gap-1.5 px-3.5 py-3 text-[11.5px]">
        <span className="flex items-center gap-2 font-medium lp-text">
          <Folder className="h-3.5 w-3.5 shrink-0 lp-tertiary" aria-hidden />
          src/
        </span>
        <div className="ml-[6px] flex flex-col gap-1.5 border-l pl-3 lp-border">
          <span className="flex items-center gap-2 lp-secondary">
            <FileCode2 className="h-3.5 w-3.5 shrink-0 lp-tertiary" aria-hidden />
            index.ts
          </span>
          <span className="flex items-center gap-2 lp-secondary">
            <FileCode2 className="h-3.5 w-3.5 shrink-0 lp-tertiary" aria-hidden />
            server.ts
          </span>
        </div>
        <span className="flex items-center gap-2 lp-secondary">
          <FileJson2 className="h-3.5 w-3.5 shrink-0 lp-tertiary" aria-hidden />
          package.json
        </span>
        <span className="flex items-center gap-2 lp-secondary">
          <Container className="h-3.5 w-3.5 shrink-0 lp-tertiary" aria-hidden />
          Dockerfile
        </span>
      </div>

      <div className="flex items-center gap-2 border-t px-3.5 py-2 lp-border">
        <GitBranch className="h-3 w-3 shrink-0 lp-tertiary" aria-hidden />
        <span className="lp-mono text-[10.5px] lp-tertiary">main</span>
        <span className="lp-mono ml-auto text-[10.5px] lp-tertiary">4 files</span>
      </div>
    </div>
  );
}

function OrchestrationPanel() {
  return (
    <div className="flex h-full flex-col items-center justify-center rounded-[10px] border p-4 lp-border lp-surface">
      <div className="flex w-full max-w-[260px] items-center gap-3 rounded-[10px] border border-[color:var(--lp-primary)] bg-[var(--lp-primary-soft)] px-4 py-4 shadow-[0_0_0_4px_rgba(37,99,235,0.06)]">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[8px] bg-[var(--lp-primary)] text-white">
          <Boxes className="h-[19px] w-[19px]" aria-hidden />
        </span>
        <span className="min-w-0">
          <span className="lp-mono block truncate text-[13.5px] font-semibold tracking-wide lp-text">
            MEDHA
          </span>
          <span className="block truncate text-[10.5px] lp-secondary">Orchestrator</span>
        </span>
      </div>

      {/* Trunk, rail and three drops down to the coordinated components. */}
      <div className="relative h-8 w-full max-w-[300px] lg:hidden xl:block" aria-hidden>
        <span className="absolute left-1/2 top-0 h-4 w-px -translate-x-1/2 bg-[var(--lp-connector)]" />
        <span className="absolute inset-x-[16%] top-4 h-px bg-[var(--lp-connector)]" />
        <span className="absolute left-[16%] top-4 h-4 w-px bg-[var(--lp-connector)]" />
        <span className="absolute left-1/2 top-4 h-4 w-px -translate-x-1/2 bg-[var(--lp-connector)]" />
        <span className="absolute right-[16%] top-4 h-4 w-px bg-[var(--lp-connector)]" />
      </div>
      {/* Narrow desktops stack the components, so only the trunk is drawn. */}
      <div className="hidden h-4 w-px bg-[var(--lp-connector)] lg:block xl:hidden" aria-hidden />

      <div className="grid w-full max-w-[300px] grid-cols-3 gap-1.5 lg:flex lg:flex-col xl:grid xl:grid-cols-3">
        {COMPONENTS.map(({ icon: Icon, label }) => (
          <div
            key={label}
            className="flex items-center justify-center gap-1.5 rounded-[6px] border px-1 py-2 lp-border lp-surface-muted lg:justify-start lg:px-2.5 xl:justify-center xl:px-1"
          >
            <Icon className="h-3 w-3 shrink-0 lp-tertiary" aria-hidden />
            <span className="truncate text-[10.5px] font-medium lp-text xl:text-[11.5px]">
              {label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ChecksPanel() {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-[10px] border lp-border lp-surface">
      <div className="flex items-center gap-2 border-b px-3.5 py-2.5 lp-border">
        <ListChecks className="h-3.5 w-3.5 shrink-0 lp-tertiary" aria-hidden />
        <span className="text-[11.5px] font-semibold lp-text">Checks</span>
      </div>
      <ul className="flex flex-1 flex-col">
        {CHECKS.map(({ icon: Icon, label }, index) => (
          <li
            key={label}
            className={`flex min-h-9 flex-1 items-center gap-2.5 px-3.5 lg:min-h-0 ${
              index > 0 ? "border-t lp-border" : ""
            }`}
          >
            <Icon className="h-3.5 w-3.5 shrink-0 lp-tertiary" aria-hidden />
            <span className="flex-1 truncate text-[12px] lp-text">{label}</span>
            <span
              className="h-3.5 w-3.5 shrink-0 rounded-[3px] border bg-[var(--lp-surface-muted)] lp-border"
              aria-hidden
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

function DeployPanel() {
  return (
    <div className="flex w-full flex-col items-center justify-center rounded-[10px] border px-4 py-7 lp-border lp-surface">
      <span className="flex h-12 w-12 items-center justify-center rounded-full border border-[color:var(--lp-primary)] bg-[var(--lp-primary-soft)]">
        <Server className="h-5 w-5 text-[color:var(--lp-primary)]" aria-hidden />
      </span>
      <span className="mt-3 text-[12.5px] font-semibold lp-text">Deploy</span>
      <span className="lp-mono mt-0.5 text-[10.5px] lp-tertiary">Local Docker host</span>
    </div>
  );
}

export function LandingPage({ signedIn }: { signedIn: boolean }) {
  const router = useRouter();
  const [dialogOpen, setDialogOpen] = useState(false);

  function start() {
    if (signedIn) {
      router.push("/projects");
      return;
    }
    setDialogOpen(true);
  }

  return (
    <div className="landing flex min-h-svh flex-col">
      <header className="h-16 shrink-0 border-b lp-border lp-surface">
        <div className="mx-auto flex h-full w-full max-w-[1600px] items-center justify-between px-[4.5%]">
          <span className="font-display text-[19px] font-bold tracking-tight lp-text">
            MEDHA
          </span>
          {signedIn ? null : (
            <Link href="/sign-in" className="lp-nav-link -mr-3">
              Sign in
            </Link>
          )}
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-[1600px] flex-1 grid-cols-1 items-center gap-12 px-[4.5%] py-10 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:gap-14 lg:py-6">
        <section aria-label="Enter MEDHA" className="min-w-0">
          <h1 className="font-display max-w-[560px] text-[clamp(2.5rem,4vw,4rem)] font-bold leading-[1.05] tracking-[-0.02em] lp-text">
            Your code.
            <br />
            Ready to deploy.
          </h1>
          <p className="mt-5 max-w-[360px] text-[15.5px] leading-relaxed lp-secondary">
            MEDHA plans, checks, and deploys your code.
          </p>
          <button
            type="button"
            onClick={start}
            className="lp-btn lp-btn-primary lp-btn-start mt-8"
            aria-label="Start MEDHA"
          >
            Start <ArrowRight className="h-4 w-4" aria-hidden />
          </button>
        </section>

        <section aria-label="Repository to deployment (conceptual)" className="min-w-0">
          <div className="rounded-2xl border p-5 lp-border lp-surface-muted lg:p-6">
            <div className="mx-auto grid w-full max-w-[480px] grid-cols-1 lg:mx-0 lg:max-w-none lg:grid-cols-[minmax(0,1fr)_44px_minmax(0,1fr)] lg:grid-rows-[250px_44px_260px] 2xl:grid-rows-[280px_48px_300px]">
              <div className="row-start-1 lg:col-start-1 lg:row-start-1">
                <RepositoryPanel />
              </div>

              <ArrowDown className="row-start-2 h-8 lg:hidden" />

              <div className="row-start-3 lg:col-start-3 lg:row-start-1">
                <OrchestrationPanel />
              </div>

              <ArrowDown className="row-start-4 h-8 lg:hidden" />

              <div className="row-start-5 lg:col-start-3 lg:row-start-3">
                <ChecksPanel />
              </div>

              <ArrowDown className="row-start-6 h-8 lg:hidden" />

              <div className="row-start-7 mx-auto w-full max-w-[320px] lg:col-start-1 lg:row-start-3 lg:max-w-none lg:self-center">
                <DeployPanel />
              </div>

              <div className="hidden lg:col-start-2 lg:row-start-1 lg:flex">
                <ArrowSide dir="right" className="h-full w-full" />
              </div>
              <div className="hidden lg:col-start-3 lg:row-start-2 lg:flex">
                <ArrowDown className="h-full w-full" />
              </div>
              <div className="hidden lg:col-start-2 lg:row-start-3 lg:flex">
                <ArrowSide dir="left" className="h-full w-full" />
              </div>
            </div>
          </div>
        </section>
      </main>

      {dialogOpen ? (
        <AuthChoiceDialog
          onClose={() => {
            setDialogOpen(false);
          }}
        />
      ) : null}
    </div>
  );
}
