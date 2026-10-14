"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/AppShell";
import {
  checkBackendHealth,
  fetchAiStatus,
  fetchConfigStatus,
  getApiBaseUrl,
  type AiStatus,
  type ConfigStatus,
} from "@/lib/api/client";

const MOTION_KEY = "medha.prefs.reduceMotion.v1";

export default function SettingsPage() {
  const [health, setHealth] = useState<boolean | null>(null);
  const [detail, setDetail] = useState<string>("");
  const [ai, setAi] = useState<AiStatus | null>(null);
  const [aiError, setAiError] = useState<string>("");
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [reduceMotion, setReduceMotion] = useState(false);

  const refresh = useCallback(() => {
    void checkBackendHealth().then((ok) => {
      setHealth(ok);
      setDetail(ok ? "API reachable." : "API not reachable.");
    });
    void fetchAiStatus().then(
      (status) => {
        setAi(status);
        setAiError("");
      },
      () => {
        setAi(null);
        setAiError("AI status unavailable (backend unreachable?).");
      },
    );
    void fetchConfigStatus().then(setConfig).catch(() => setConfig(null));
  }, []);

  useEffect(() => {
    refresh();
    try {
      setReduceMotion(window.localStorage.getItem(MOTION_KEY) === "1");
    } catch {
      /* prefs unavailable */
    }
  }, [refresh]);

  function saveMotion(next: boolean) {
    setReduceMotion(next);
    try {
      window.localStorage.setItem(MOTION_KEY, next ? "1" : "0");
      document.documentElement.style.setProperty("scroll-behavior", next ? "auto" : "");
    } catch {
      /* noop */
    }
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-2xl space-y-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-medha-text">
            Settings
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-medha-secondary">
            Local-product settings only. MEDHA V1 keeps configuration minimal by design:
            one FastAPI process, one Next.js app, SQLite (or configured PostgreSQL), and local Docker.
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
            AI assistance
          </h2>
          {aiError ? (
            <p className="mt-2 text-sm text-medha-secondary">{aiError}</p>
          ) : ai == null ? (
            <p className="mt-2 text-sm text-medha-secondary">Checking AI provider status…</p>
          ) : (
            <dl className="mt-3 grid gap-3 sm:grid-cols-2">
              <div className="rounded-medha-sm border border-medha-border bg-medha-muted px-3 py-2">
                <dt className="medha-label">Mode</dt>
                <dd className="mt-1 text-sm font-semibold text-medha-text">
                  {ai.enabled ? "AI-assisted (advisory)" : "Rule-based (deterministic)"}
                </dd>
                <p className="mt-0.5 text-xs text-medha-tertiary">
                  AI notes are advisory only; deterministic gates always decide.
                </p>
              </div>
              <div className="rounded-medha-sm border border-medha-border bg-medha-muted px-3 py-2">
                <dt className="medha-label">Providers</dt>
                <dd className="medha-mono mt-1 text-xs text-medha-text">
                  {ai.primary_provider}/{ai.primary_model} → {ai.fallback_provider}/
                  {ai.fallback_model}
                </dd>
                <p className="mt-0.5 text-xs text-medha-tertiary">
                  {["groq", "gemini"]
                    .map((name) => {
                      const p = ai.health.providers[name];
                      if (!p || !p.configured) return `${name}: no key`;
                      return `${name}: ${p.reachable ? "reachable" : `unreachable (${p.failure_category ?? "unknown"})`}`;
                    })
                    .join(" · ")}
                </p>
              </div>
            </dl>
          )}
          <p className="mt-2 text-xs text-medha-tertiary">
            Budget: {ai?.max_calls_per_run ?? "—"} calls per run · timeout{" "}
            {ai?.request_timeout_seconds ?? "—"}s · max {ai?.max_output_tokens ?? "—"}{" "}
            tokens. Enable with MEDHA_AI_ENABLED + provider keys (server-only env).
          </p>
        </section>

        <section className="medha-panel animate-medha-in p-4 sm:p-5">
          <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
            Run modes
          </h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div className="rounded-medha-sm border border-medha-border bg-medha-muted p-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-medha-secondary">
                DEMO / MOCK (removed)
              </p>
              <p className="mt-1 text-xs leading-relaxed text-medha-text">
                Demo execution was removed from the product. Historical
                DEMO/MOCK records keep their labels; no new demo runs can be
                created.
              </p>
            </div>
            <div className="rounded-medha-sm border border-medha-run/25 bg-medha-run-soft p-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-medha-run-ink">
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
            Execution configuration
          </h2>
          {config == null ? (
            <p className="mt-2 text-sm text-medha-secondary">
              Unavailable — the backend did not report configuration status.
            </p>
          ) : (
            <>
              <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                <div className="rounded-medha-sm border border-medha-border bg-medha-muted px-3 py-2">
                  <dt className="medha-label">Executor mode</dt>
                  <dd className="medha-mono mt-1 text-xs text-medha-text">{config.executor_mode}</dd>
                  <p className="mt-0.5 text-[11px] text-medha-tertiary">
                    Docker execution {config.docker_execute ? "enabled" : "disabled"} · environment {config.env}
                  </p>
                </div>
                <div className="rounded-medha-sm border border-medha-border bg-medha-muted px-3 py-2">
                  <dt className="medha-label">Readiness</dt>
                  <dd className="mt-1 flex items-center gap-2 text-sm font-semibold text-medha-text">
                    <span
                      className={`status-dot ${
                        config.execution_readiness == null
                          ? "bg-medha-tertiary"
                          : config.execution_readiness.status === "ready"
                            ? "bg-medha-success"
                            : config.execution_readiness.status === "blocked"
                              ? "bg-medha-danger"
                              : "bg-medha-warning"
                      }`}
                      aria-hidden
                    />
                    {config.execution_readiness == null
                      ? "not reported"
                      : config.execution_readiness.status}
                  </dd>
                  {config.execution_readiness ? (
                    <p className="medha-mono mt-0.5 text-[11px] text-medha-tertiary">
                      {config.execution_readiness.reason_code}
                    </p>
                  ) : null}
                </div>
              </dl>
              {config.execution_readiness ? (
                <div className="mt-3 space-y-2">
                  <p className="text-sm leading-relaxed text-medha-secondary">
                    {config.execution_readiness.message}
                  </p>
                  {config.execution_readiness.next_actions.length > 0 ? (
                    <ul className="list-inside list-disc space-y-0.5 text-sm text-medha-secondary">
                      {config.execution_readiness.next_actions.map((action) => (
                        <li key={action}>{action}</li>
                      ))}
                    </ul>
                  ) : null}
                  {config.execution_readiness.requires_operator ||
                  config.execution_readiness.restart_required ? (
                    <p className="medha-label">
                      {[
                        config.execution_readiness.requires_operator
                          ? "backend/operator change required"
                          : null,
                        config.execution_readiness.restart_required ? "backend restart required" : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  ) : null}
                </div>
              ) : null}
              <p className="mt-3 text-xs text-medha-tertiary">
                Server-side environment only (MEDHA_EXECUTOR_MODE, MEDHA_DOCKER_EXECUTE).
                Presence and readiness only — no environment values or secrets are shown here.
              </p>
            </>
          )}
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
            <li>SQLite by default (PostgreSQL when MEDHA_DATABASE_URL is configured). No Redis, Kubernetes, or CI/CD automation in V1.</li>
            <li>Demo results are always labelled; real results are never faked.</li>
          </ul>
        </section>

        <section className="medha-panel animate-medha-in p-4 sm:p-5">
          <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
            Appearance & accessibility
          </h2>
          <div className="mt-3 space-y-3">
            <div className="rounded-lg border border-medha-border px-3 py-2.5">
              <p className="text-sm font-medium text-medha-text">Bright theme</p>
              <p className="text-xs text-medha-secondary">MEDHA V1 ships bright-only; there is no dark mode.</p>
            </div>
            <div className="flex items-center justify-between gap-3 rounded-lg border border-medha-border px-3 py-2.5">
              <div>
                <p className="text-sm font-medium text-medha-text">Reduce motion</p>
                <p className="text-xs text-medha-secondary">Disables smooth scrolling and entrance motion.</p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={reduceMotion}
                onClick={() => saveMotion(!reduceMotion)}
                className={`relative h-6 w-11 rounded-full transition ${reduceMotion ? "bg-medha-accent" : "bg-medha-border-strong"}`}
              >
                <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${reduceMotion ? "left-[22px]" : "left-0.5"}`} aria-hidden />
              </button>
            </div>
            <p className="text-xs text-medha-secondary">Keyboard: all flows are keyboard-navigable with visible focus. Status is never color-only. Graphs include list alternatives.</p>
          </div>
        </section>

        <section className="medha-panel animate-medha-in p-4 sm:p-5">
          <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
            Application
          </h2>
          <dl className="mt-3 space-y-1.5 text-sm text-medha-secondary">
            <div className="flex justify-between gap-3"><dt>Product</dt><dd className="text-medha-text">MEDHA V1 research prototype</dd></div>
            <div className="flex justify-between gap-3"><dt>Workspaces</dt><dd><Link href="/projects" className="text-medha-accent hover:underline">Open Projects →</Link></dd></div>
            <div className="flex justify-between gap-3"><dt>Scope</dt><dd className="text-right">Local Docker · SQLite/PG · no cloud/K8s/Redis</dd></div>
          </dl>
        </section>
      </div>
    </AppShell>
  );
}