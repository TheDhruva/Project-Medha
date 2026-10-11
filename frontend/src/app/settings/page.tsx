"use client";

import { useCallback, useEffect, useState } from "react";
import { Header } from "@/components/layout/Header";
import { checkBackendHealth, getApiBaseUrl } from "@/lib/api/client";

export default function SettingsPage() {
  const [health, setHealth] = useState<boolean | null>(null);
  const [detail, setDetail] = useState<string>("");

  const refresh = useCallback(() => {
    void checkBackendHealth().then((ok) => {
      setHealth(ok);
      setDetail(ok ? "API reachable." : "API not reachable.");
    });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className="min-h-screen bg-medha-bg">
      <Header />
      <main className="mx-auto max-w-2xl space-y-4 px-4 py-8 sm:px-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-medha-text">
            Settings
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-medha-secondary">
            Local-product settings only. MEDHA V1 keeps configuration minimal by design:
            one FastAPI process, one Next.js app, SQLite, and local Docker.
          </p>
        </div>

        <section className="medha-panel animate-medha-in p-4 sm:p-5">
          <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
            Backend connection
          </h2>
          <dl className="mt-3 grid gap-3 sm:grid-cols-2">
            <div className="rounded-medha-sm border border-medha-border bg-medha-muted px-3 py-2">
              <dt className="medha-label">API base URL</dt>
              <dd className="medha-mono mt-1 text-xs text-medha-text">{getApiBaseUrl() || "(same origin)"}</dd>
            </div>
            <div className="rounded-medha-sm border border-medha-border bg-medha-muted px-3 py-2">
              <dt className="medha-label">Health</dt>
              <dd className="mt-1 flex items-center gap-2 text-sm font-semibold text-medha-text">
                <span
                  className={`status-dot ${health == null ? "bg-medha-tertiary" : health ? "bg-medha-success" : "bg-medha-danger"}`}
                  aria-hidden
                />
                {health == null ? "checking…" : health ? "OK" : "Unreachable"}
              </dd>
              <p className="mt-0.5 text-xs text-medha-tertiary">{detail}</p>
            </div>
          </dl>
          <button
            type="button"
            onClick={refresh}
            className="mt-3 rounded-medha-sm border border-medha-border bg-white px-3 py-2 text-sm font-medium text-medha-secondary hover:bg-medha-muted"
          >
            Re-check
          </button>
        </section>

        <section className="medha-panel animate-medha-in p-4 sm:p-5">
          <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
            Run modes
          </h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div className="rounded-medha-sm border border-medha-accent/25 bg-medha-accent-soft p-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-medha-accent-ink">
                DEMO / MOCK
              </p>
              <p className="mt-1 text-xs leading-relaxed text-medha-text">
                Simulated pipeline for a college demonstration. Every payload, event, and UI
                element is explicitly labelled DEMO/MOCK. Values are fixtures, never presented as
                real execution evidence.
              </p>
            </div>
            <div className="rounded-medha-sm border border-medha-success/30 bg-medha-success-soft p-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-medha-success">
                REAL / LIVE
              </p>
              <p className="mt-1 text-xs leading-relaxed text-medha-text">
                Local pipeline against a real local git repository. Analysis, verification,
                execution, and evidence reflect real Docker/git outcomes. One real deployment at a
                time.
              </p>
            </div>
          </div>
        </section>

        <section className="medha-panel animate-medha-in p-4 sm:p-5">
          <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
            Architecture principles (V1)
          </h2>
          <ul className="mt-3 list-inside list-disc space-y-1 text-sm text-medha-secondary">
            <li>
              Deterministic logic over unnecessary LLM calls — LLM mediation only for same-priority
              CNP conflicts, max 3 negotiation rounds.
            </li>
            <li>CIG (change impact) and CEG (execution causality) are distinct, labelled graphs.</li>
            <li>Rollback is dependency-aware and preserves causally independent successes.</li>
            <li>No Redis, PostgreSQL, Kubernetes, or CI/CD automation in V1.</li>
            <li>Demo results are always labelled; real results are never faked.</li>
          </ul>
        </section>
      </main>
    </div>
  );
}