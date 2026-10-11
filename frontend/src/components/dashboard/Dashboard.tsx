"use client";

import Link from "next/link";
import { ArrowRight, FileSearch, ShieldCheck, Swords, Rocket } from "lucide-react";
import { Header } from "@/components/layout/Header";
import { RecentRuns } from "@/components/runs/RecentRuns";

const STEPS = [
  {
    n: "01",
    icon: FileSearch,
    title: "Analyze",
    text: "Understand the change",
  },
  {
    n: "02",
    icon: Swords,
    title: "Resolve",
    text: "Handle conflicts",
  },
  {
    n: "03",
    icon: ShieldCheck,
    title: "Verify",
    text: "Check safety",
  },
  {
    n: "04",
    icon: Rocket,
    title: "Deploy",
    text: "Execute with evidence",
  },
];

export function Dashboard() {
  return (
    <div className="min-h-screen bg-medha-bg">
      <Header />
      <main className="mx-auto max-w-3xl space-y-10 px-4 py-10 sm:px-6 sm:py-14">
        {/* HERO */}
        <section className="text-center">
          <h1 className="text-4xl font-bold tracking-tight text-medha-text sm:text-5xl">
            MEDHA
          </h1>
          <p className="mt-3 text-xl text-medha-text sm:text-2xl">
            Deploy infrastructure changes with confidence.
          </p>
          <p className="mx-auto mt-3 max-w-xl text-[15px] leading-relaxed text-medha-secondary">
            Medha analyzes changes, resolves conflicts, verifies deployment plans,
            and records the evidence behind each decision.
          </p>
          <Link
            href="/verify"
            className="mt-6 inline-flex items-center gap-2 rounded-lg bg-medha-accent px-6 py-3 text-[15px] font-semibold text-white transition hover:bg-medha-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
          >
            Start verification <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
        </section>

        {/* HOW IT WORKS */}
        <section aria-label="How it works">
          <h2 className="text-center text-sm font-semibold uppercase tracking-[0.12em] text-medha-tertiary">
            How it works
          </h2>
          <ol className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {STEPS.map((s) => (
              <li
                key={s.n}
                className="rounded-xl border border-medha-border bg-white px-4 py-5 text-center"
              >
                <s.icon className="mx-auto h-5 w-5 text-medha-accent" aria-hidden />
                <p className="medha-mono mt-3 text-[11px] text-medha-tertiary">{s.n}</p>
                <p className="mt-0.5 text-[15px] font-semibold text-medha-text">{s.title}</p>
                <p className="mt-0.5 text-xs text-medha-secondary">{s.text}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* RECENT RUNS */}
        <section aria-label="Recent runs">
          <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-medha-tertiary">
            Recent runs
          </h2>
          <div className="mt-3">
            <RecentRuns limit={3} />
          </div>
        </section>

        <footer className="pt-4 text-center text-[11px] text-medha-tertiary">
          MEDHA · Verifiable DevOps Automation
        </footer>
      </main>
    </div>
  );
}
