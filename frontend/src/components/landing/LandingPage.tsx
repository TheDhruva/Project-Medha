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
import { MedhaFace } from "@/components/medha/MedhaFace";

function ArchNode({
  step,
  icon: Icon,
  title,
  detail,
  featured,
  className,
}: {
  step: string;
  icon: typeof Cpu;
  title: string;
  detail: string;
  featured?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 rounded-[10px] px-3 py-2 text-left",
        featured ? "lp-stage-featured" : "lp-stage",
        className,
      )}
    >
      <span
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
          featured ? "lp-chip-featured" : "lp-surface lp-text border lp-border",
        )}
        aria-hidden
      >
        <Icon className="h-4 w-4" />
      </span>
      <span className="min-w-0">
        <span className="flex items-center gap-1.5">
          <span className="lp-mono text-[10px] font-medium lp-tertiary">{step}</span>
          <span className="truncate text-[13px] font-semibold lp-text">{title}</span>
        </span>
        <span className="lp-mono block truncate text-[11px] lp-secondary">{detail}</span>
      </span>
    </div>
  );
}

function Connector({ className }: { className?: string }) {
  return (
    <div className={cn("flex justify-center", className)} aria-hidden>
      <span className="lp-connector block h-3.5 w-px sm:h-4" />
    </div>
  );
}

export function LandingPage({ signedIn }: { signedIn: boolean }) {
  return (
    <div className="landing flex min-h-svh flex-col">
      {/* Header — 64px, wordmark + descriptor + product links */}
      <header className="h-16 shrink-0 border-b lp-border lp-surface">
        <div className="flex h-full w-full items-center justify-between px-[4.5%]">
          <div className="flex items-center gap-2.5">
            <span className="font-display text-[19px] font-bold tracking-tight lp-text">
              MEDHA
            </span>
            <span aria-hidden className="lp-connector h-4 w-px" />
            <span className="text-[11px] font-medium uppercase tracking-[0.14em] lp-tertiary">
              DevOps Orchestration
            </span>
          </div>
          <p className="lp-mono hidden text-[11px] lp-tertiary sm:block">
            local-first · evidence-traced
          </p>
          <nav aria-label="Product" className="hidden items-center gap-1 md:flex">
            {[
              { href: "/projects", label: "Project Hub" },
              { href: "/runs", label: "Run History" },
              { href: "/settings", label: "Settings" },
            ].map((l) => (
              <Link key={l.href} href={l.href} className="lp-nav-link">
                {l.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>

      {/* Main — two columns, fills remaining viewport */}
      <main className="mx-auto grid w-full max-w-none flex-1 grid-cols-1 items-center gap-8 px-[4.5%] py-6 lg:h-[calc(100svh-4rem)] lg:grid-cols-[44%_56%] lg:gap-12 lg:overflow-hidden lg:py-4 xl:gap-16">
        {/* Left — entry */}
        <section aria-label="Enter MEDHA" className="min-w-0">
          <p className="lp-mono lp-eyebrow flex items-center gap-2.5 text-[11px] font-medium uppercase tracking-[0.14em]">
            <MedhaFace state="idle" size={30} />
            Constraint-aware DevOps automation
          </p>
          <p className="font-display mt-2 text-[clamp(2.75rem,4.5vw,4.25rem)] font-bold leading-[0.95] tracking-tight lp-text">
            MEDHA
          </p>
          <h1 className="mt-2 max-w-md text-[clamp(1.15rem,1.8vw,1.6rem)] font-semibold leading-snug tracking-tight lp-text">
            Infrastructure that reasons before it deploys.
          </h1>
          <p className="mt-2 max-w-md text-[13.5px] leading-relaxed lp-secondary">
            MEDHA coordinates specialized agents to analyze repositories, resolve
            infrastructure conflicts, verify deployment plans, and execute deployment
            workflows with traceable evidence.
          </p>

          <h2 className="mt-5 text-[12px] font-semibold uppercase tracking-[0.1em] lp-text">
            Choose how to enter
          </h2>
          <div className="mt-2 flex max-w-md flex-col gap-2">
            {signedIn ? (
              <Link
                href="/projects"
                className="lp-btn lp-btn-primary"
                aria-label="Start MEDHA"
              >
                Start <ArrowRight className="h-4 w-4" aria-hidden />
              </Link>
            ) : (
              <>
                <Link
                  href="/projects"
                  className="lp-btn lp-btn-primary"
                  aria-label="Continue as Guest"
                >
                  Continue as Guest <ArrowRight className="h-4 w-4" aria-hidden />
                </Link>
                <Link
                  href="/sign-in"
                  className="lp-btn lp-btn-secondary"
                  aria-label="Sign In"
                >
                  Sign In
                </Link>
              </>
            )}
          </div>
          <p className="mt-2 max-w-md text-[12px] leading-relaxed lp-tertiary">
            No registration needed to explore. Sign in keeps durable per-user projects.
          </p>
        </section>

        {/* Right — illustrative architecture diagram */}
        <section
          aria-label="MEDHA orchestration architecture (illustrative)"
          className="lp-panel min-w-0 rounded-[8px] p-4 sm:p-5 lg:max-h-full lg:overflow-hidden"
        >
          <div className="flex items-center justify-between gap-3">
            <p className="lp-label">Pipeline architecture</p>
            <span className="lp-mono rounded-full border lp-border lp-surface-muted px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.1em] lp-secondary">
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
              featured
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
                  className="lp-stage flex flex-col items-center gap-1 rounded-[10px] px-2 py-2 text-center"
                >
                  <span
                    className="lp-surface flex h-7 w-7 items-center justify-center rounded-lg border lp-border lp-text"
                    aria-hidden
                  >
                    <a.icon className="h-3.5 w-3.5" />
                  </span>
                  <span className="text-[12px] font-semibold lp-text">{a.title}</span>
                  <span className="lp-mono text-[10px] leading-tight lp-tertiary">
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

          <p className="lp-mono mt-3 border-t lp-border pt-2 text-[10.5px] leading-relaxed lp-tertiary">
            analyze → negotiate → verify → execute → recover · every action traced
          </p>
        </section>
      </main>
    </div>
  );
}
