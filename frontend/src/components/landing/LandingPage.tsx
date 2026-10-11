"use client";

import Link from "next/link";
import {
  ArrowRight,
  BadgeCheck,
  Container,
  Cpu,
  GitBranch,
  Globe,
  Rocket,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/ui/cn";

function ArchNode({
  step,
  icon: Icon,
  title,
  detail,
  accent,
  className,
}: {
  step: string;
  icon: typeof Cpu;
  title: string;
  detail: string;
  accent?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 rounded-[10px] border bg-white px-3 py-2 text-left",
        accent ? "border-medha-accent/40 shadow-medha" : "border-medha-border",
        className,
      )}
    >
      <span
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
          accent ? "bg-medha-accent text-white" : "bg-medha-muted text-medha-text",
        )}
        aria-hidden
      >
        <Icon className="h-4 w-4" />
      </span>
      <span className="min-w-0">
        <span className="flex items-center gap-1.5">
          <span className="medha-mono text-[10px] font-medium text-medha-tertiary">{step}</span>
          <span className="truncate text-[13px] font-semibold text-medha-text">{title}</span>
        </span>
        <span className="medha-mono block truncate text-[11px] text-medha-secondary">{detail}</span>
      </span>
    </div>
  );
}

function Connector({ className }: { className?: string }) {
  return (
    <div className={cn("flex justify-center", className)} aria-hidden>
      <span className="block h-3.5 w-px bg-medha-border-strong sm:h-4" />
    </div>
  );
}

export function LandingPage({ signedIn }: { signedIn: boolean }) {
  return (
    <div className="flex min-h-svh flex-col bg-medha-bg">
      {/* Header — 64px, wordmark + product label only */}
      <header className="h-16 shrink-0 border-b border-medha-border bg-white">
        <div className="flex h-full w-full items-center justify-between px-[4.5%]">
          <div className="flex items-center gap-2.5">
            <span className="font-display text-[19px] font-bold tracking-tight text-medha-text">
              MEDHA
            </span>
            <span aria-hidden className="h-4 w-px bg-medha-border-strong" />
            <span className="text-[11px] font-medium uppercase tracking-[0.14em] text-medha-tertiary">
              DevOps Orchestration
            </span>
          </div>
          <p className="medha-mono hidden text-[11px] text-medha-tertiary sm:block">
            local-first · evidence-traced
          </p>
        </div>
      </header>

      {/* Main — two columns, fills remaining viewport */}
      <main className="mx-auto grid w-full max-w-none flex-1 grid-cols-1 items-center gap-8 px-[4.5%] py-6 lg:h-[calc(100svh-4rem)] lg:grid-cols-[44%_56%] lg:gap-12 lg:overflow-hidden lg:py-4 xl:gap-16">
        {/* Left — entry */}
        <section aria-label="Enter MEDHA" className="min-w-0">
          <p className="medha-mono flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.14em] text-medha-accent">
            <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full bg-medha-accent" />
            Constraint-aware DevOps automation
          </p>
          <p className="font-display mt-2 text-[clamp(2.75rem,4.5vw,4.25rem)] font-bold leading-[0.95] tracking-tight text-medha-text">
            MEDHA
          </p>
          <h1 className="mt-2 max-w-md text-[clamp(1.15rem,1.8vw,1.6rem)] font-semibold leading-snug tracking-tight text-medha-text">
            Infrastructure that reasons before it deploys.
          </h1>
          <p className="mt-2 max-w-md text-[13.5px] leading-relaxed text-medha-secondary">
            MEDHA coordinates specialized agents to analyze repositories, resolve
            infrastructure conflicts, verify deployment plans, and execute deployment
            workflows with traceable evidence.
          </p>

          <h2 className="mt-5 text-[12px] font-semibold uppercase tracking-[0.1em] text-medha-text">
            Choose how to enter
          </h2>
          <div className="mt-2 flex max-w-md flex-col gap-2">
            {signedIn ? (
              <Link
                href="/projects"
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-[10px] bg-medha-accent px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-medha-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
                aria-label="Start MEDHA"
              >
                Start <ArrowRight className="h-4 w-4" aria-hidden />
              </Link>
            ) : (
              <>
                <Link
                  href="/demo"
                  className="inline-flex w-full items-center justify-center gap-1.5 rounded-[10px] bg-medha-accent px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-medha-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
                  aria-label="Continue as Guest"
                >
                  Continue as Guest <ArrowRight className="h-4 w-4" aria-hidden />
                </Link>
                <Link
                  href="/sign-in"
                  className="inline-flex w-full items-center justify-center gap-1.5 rounded-[10px] border border-medha-border-strong bg-white px-5 py-2.5 text-sm font-semibold text-medha-text transition hover:bg-medha-muted/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
                  aria-label="Sign In"
                >
                  Sign In
                </Link>
              </>
            )}
          </div>
          <p className="mt-2 max-w-md text-[12px] leading-relaxed text-medha-tertiary">
            Guest runs the labeled simulated demo — no registration. Sign in keeps
            durable per-user projects.
          </p>
        </section>

        {/* Right — illustrative architecture diagram */}
        <section
          aria-label="MEDHA orchestration architecture (illustrative)"
          className="min-w-0 rounded-medha border border-medha-border bg-medha-surface p-4 shadow-medha sm:p-5 lg:max-h-full lg:overflow-hidden"
        >
          <div className="flex items-center justify-between gap-3">
            <p className="medha-label">Pipeline architecture</p>
            <span className="medha-mono rounded-full border border-medha-border bg-medha-muted px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.1em] text-medha-secondary">
              Illustrative
            </span>
          </div>

          <div className="mt-3">
            <ArchNode
              step="01"
              icon={GitBranch}
              title="Repository & Constraints"
              detail="repo url · ports · env · policy"
            />
            <Connector />
            <ArchNode
              step="02"
              icon={Cpu}
              title="MEDHA Orchestrator"
              detail="constraint negotiation · ≤ 3 rounds"
              accent
            />
            <Connector />
            <div
              className="grid grid-cols-3 gap-2"
              aria-label="Specialized agents: Docker, Network, Security"
            >
              {[
                { icon: Container, title: "Docker", detail: "image · ports" },
                { icon: Globe, title: "Network", detail: "nginx · routes" },
                { icon: ShieldCheck, title: "Security", detail: "policy · secrets" },
              ].map((a) => (
                <div
                  key={a.title}
                  className="flex flex-col items-center gap-1 rounded-[10px] border border-medha-border bg-white px-2 py-2 text-center"
                >
                  <span
                    className="flex h-7 w-7 items-center justify-center rounded-lg bg-medha-muted text-medha-text"
                    aria-hidden
                  >
                    <a.icon className="h-3.5 w-3.5" />
                  </span>
                  <span className="text-[12px] font-semibold text-medha-text">{a.title}</span>
                  <span className="medha-mono text-[10px] leading-tight text-medha-tertiary">
                    {a.detail}
                  </span>
                </div>
              ))}
            </div>
            <Connector />
            <ArchNode
              step="04"
              icon={BadgeCheck}
              title="Verification"
              detail="verifier + critic gates before execute"
            />
            <Connector />
            <ArchNode
              step="05"
              icon={Rocket}
              title="Execution & Recovery"
              detail="CEG evidence · scoped rollback"
            />
          </div>

          <p className="medha-mono mt-3 border-t border-medha-border pt-2 text-[10.5px] leading-relaxed text-medha-tertiary">
            analyze → negotiate → verify → execute → recover · every action traced
          </p>
        </section>
      </main>
    </div>
  );
}