"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Check,
  Cpu,
  ExternalLink,
  GitBranch,
  Globe,
  HardDrive,
  Layers,
  Palette,
  RefreshCw,
  Server,
  Shield,
  Sliders,
} from "lucide-react";
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
  const [checkingHealth, setCheckingHealth] = useState(false);
  const [ai, setAi] = useState<AiStatus | null>(null);
  const [aiError, setAiError] = useState<string>("");
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [reduceMotion, setReduceMotion] = useState(false);

  const refresh = useCallback(() => {
    setCheckingHealth(true);
    void checkBackendHealth()
      .then((ok) => setHealth(ok))
      .finally(() => setCheckingHealth(false));

    void fetchAiStatus().then(
      (status) => {
        setAi(status);
        setAiError("");
      },
      () => {
        setAi(null);
        setAiError("AI provider status is currently unavailable.");
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

  const readiness = config?.execution_readiness;
  const dockerReady = readiness?.status === "ready";
  const dockerBlocked = readiness?.status === "blocked";

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl space-y-8 pb-12">
        {/* Page Header */}
        <div>
          <h1 className="text-[26px] font-semibold tracking-tight text-medha-text">
            Settings
          </h1>
          <p className="mt-1 text-[13.5px] text-medha-secondary">
            Manage workspace connectivity, AI assistance, execution readiness, and accessibility preferences.
          </p>
        </div>

        {/* 1. General */}
        <section aria-labelledby="section-general" className="space-y-3">
          <div className="border-b border-medha-border pb-2">
            <h2 id="section-general" className="text-[15px] font-semibold text-medha-text">
              General
            </h2>
          </div>

          <div className="rounded-xl border border-medha-border bg-white divide-y divide-medha-border/60">
            <div className="flex items-center justify-between p-4 text-[13px]">
              <div>
                <p className="font-medium text-medha-text">MEDHA Prototype</p>
                <p className="text-medha-secondary">Version 1.0 · Local-first verifiable DevOps automation</p>
              </div>
              <span className="rounded-md border border-medha-border bg-medha-surface-muted px-2 py-0.5 text-[11px] font-mono text-medha-secondary">
                v1.0-research
              </span>
            </div>

            <div className="flex items-center justify-between p-4 text-[13px]">
              <div>
                <p className="font-medium text-medha-text">Active workspace</p>
                <p className="text-medha-secondary">Direct repository analysis and execution</p>
              </div>
              <Link
                href="/projects"
                className="inline-flex items-center gap-1 text-[13px] font-medium text-medha-accent hover:underline"
              >
                Open Projects
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              </Link>
            </div>
          </div>
        </section>

        {/* 2. Connections */}
        <section aria-labelledby="section-connections" className="space-y-3">
          <div className="border-b border-medha-border pb-2">
            <h2 id="section-connections" className="text-[15px] font-semibold text-medha-text">
              Connections
            </h2>
          </div>

          <div className="rounded-xl border border-medha-border bg-white divide-y divide-medha-border/60">
            {/* Backend API */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 text-[13px]">
              <div>
                <div className="flex items-center gap-2">
                  <p className="font-medium text-medha-text">FastAPI Backend</p>
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium ${
                      health === null
                        ? "border-medha-border bg-medha-surface-muted text-medha-secondary"
                        : health
                          ? "border-medha-success/30 bg-medha-success-soft text-medha-success"
                          : "border-medha-danger/30 bg-medha-danger-soft text-medha-danger"
                    }`}
                  >
                    <span
                      aria-hidden
                      className={`h-1.5 w-1.5 rounded-full ${
                        health === null ? "bg-medha-tertiary" : health ? "bg-medha-success" : "bg-medha-danger"
                      }`}
                    />
                    {health === null ? "Checking…" : health ? "Connected" : "Unreachable"}
                  </span>
                </div>
                <p className="mt-1 font-mono text-[12px] text-medha-secondary">
                  {getApiBaseUrl() || "(same origin)"}
                </p>
              </div>

              <button
                type="button"
                onClick={refresh}
                disabled={checkingHealth}
                className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-medha-border bg-white px-3 py-1.5 text-[12.5px] font-medium text-medha-secondary hover:bg-medha-surface-muted hover:text-medha-text disabled:opacity-50"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${checkingHealth ? "animate-spin" : ""}`} aria-hidden />
                Check connection
              </button>
            </div>

            {/* GitHub Integration */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 text-[13px]">
              <div>
                <div className="flex items-center gap-2">
                  <p className="font-medium text-medha-text">GitHub Integration</p>
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-medha-border bg-medha-surface-muted px-2 py-0.5 text-[11px] font-medium text-medha-secondary">
                    <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-medha-secondary" />
                    {config?.github_app_configured ? "GitHub App configured" : "Public access"}
                  </span>
                </div>
                <p className="mt-1 text-[12.5px] text-medha-secondary">
                  {config?.github_app_configured
                    ? "Authentication configured for private and public repository verification."
                    : "Direct read-only inspection via git ls-remote for public repositories."}
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* 3. AI Providers */}
        <section aria-labelledby="section-ai" className="space-y-3">
          <div className="border-b border-medha-border pb-2">
            <h2 id="section-ai" className="text-[15px] font-semibold text-medha-text">
              AI Providers
            </h2>
          </div>

          <div className="rounded-xl border border-medha-border bg-white p-4 space-y-4 text-[13px]">
            {aiError ? (
              <p className="text-medha-secondary">{aiError}</p>
            ) : ai === null ? (
              <div className="flex items-center gap-2 text-medha-secondary">
                <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden />
                <span>Checking AI provider status…</span>
              </div>
            ) : (
              <>
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-medha-border/60 pb-3">
                  <div>
                    <p className="font-medium text-medha-text">Assistance Mode</p>
                    <p className="text-[12.5px] text-medha-secondary">
                      {ai.enabled
                        ? "AI assistance is active for advisory suggestions; deterministic gates always decide."
                        : "Deterministic mode: rule-based engines and verified gates only."}
                    </p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${
                      ai.enabled
                        ? "border-medha-accent/30 bg-medha-accent-soft text-medha-accent-hover"
                        : "border-medha-border bg-medha-surface-muted text-medha-secondary"
                    }`}
                  >
                    {ai.enabled ? "Advisory (AI)" : "Deterministic"}
                  </span>
                </div>

                {/* Configured Providers */}
                <div>
                  <p className="font-medium text-medha-text mb-2">Configured Models</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {["groq", "gemini"].map((name) => {
                      const p = ai.health.providers[name];
                      const configured = p?.configured ?? false;
                      const reachable = p?.reachable ?? false;
                      const model = name === "groq" ? ai.primary_model : ai.fallback_model;

                      return (
                        <div
                          key={name}
                          className="rounded-lg border border-medha-border/80 bg-medha-canvas/40 p-3"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-medium capitalize text-medha-text">{name}</span>
                            <span
                              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-medium ${
                                !configured
                                  ? "bg-medha-surface-muted text-medha-tertiary"
                                  : reachable
                                    ? "bg-medha-success-soft text-medha-success"
                                    : "bg-medha-warning-soft text-medha-warning"
                              }`}
                            >
                              <span
                                aria-hidden
                                className={`h-1.5 w-1.5 rounded-full ${
                                  !configured
                                    ? "bg-medha-tertiary"
                                    : reachable
                                      ? "bg-medha-success"
                                      : "bg-medha-warning"
                                }`}
                              />
                              {!configured ? "Not configured" : reachable ? "Reachable" : "Unreachable"}
                            </span>
                          </div>
                          <p className="mt-1 font-mono text-[11.5px] text-medha-secondary truncate">
                            {configured ? model : "No API key configured"}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Resource Limits */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-1 text-[12px] text-medha-tertiary">
                  <span>Budget: {ai.max_calls_per_run} calls/run</span>
                  <span>·</span>
                  <span>Timeout: {ai.request_timeout_seconds}s</span>
                  <span>·</span>
                  <span>Max tokens: {ai.max_output_tokens}</span>
                </div>
              </>
            )}
          </div>
        </section>

        {/* 4. Execution */}
        <section aria-labelledby="section-execution" className="space-y-3">
          <div className="border-b border-medha-border pb-2">
            <h2 id="section-execution" className="text-[15px] font-semibold text-medha-text">
              Execution
            </h2>
          </div>

          <div className="rounded-xl border border-medha-border bg-white p-4 space-y-4 text-[13px]">
            {config === null ? (
              <p className="text-medha-secondary">Configuration status unavailable.</p>
            ) : (
              <>
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="font-medium text-medha-text">Docker Execution</p>
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium ${
                          dockerReady
                            ? "border-medha-success/30 bg-medha-success-soft text-medha-success"
                            : dockerBlocked
                              ? "border-medha-danger/30 bg-medha-danger-soft text-medha-danger"
                              : "border-medha-warning/30 bg-medha-warning-soft text-medha-warning"
                        }`}
                      >
                        <span
                          aria-hidden
                          className={`h-1.5 w-1.5 rounded-full ${
                            dockerReady
                              ? "bg-medha-success"
                              : dockerBlocked
                                ? "bg-medha-danger"
                                : "bg-medha-warning"
                          }`}
                        />
                        {readiness?.status ? readiness.status.charAt(0).toUpperCase() + readiness.status.slice(1) : "Unknown"}
                      </span>
                    </div>
                    <p className="mt-1 text-[12.5px] text-medha-secondary">
                      Supported profiles: <span className="font-medium text-medha-text">Node.js, Python, static</span>
                    </p>
                  </div>

                  <button
                    type="button"
                    onClick={refresh}
                    className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-medha-border bg-white px-3 py-1.5 text-[12.5px] font-medium text-medha-secondary hover:bg-medha-surface-muted hover:text-medha-text"
                  >
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                    Check readiness
                  </button>
                </div>

                {readiness && !dockerReady ? (
                  <div className="rounded-lg border border-medha-warning/40 bg-medha-warning-soft/50 p-3 space-y-2">
                    <p className="text-[12.5px] font-medium text-medha-warning">
                      {readiness.message}
                    </p>
                    {readiness.next_actions.length > 0 ? (
                      <ul className="list-inside list-disc space-y-0.5 text-[12px] text-medha-secondary">
                        {readiness.next_actions.map((act) => (
                          <li key={act}>{act}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ) : null}

                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-medha-tertiary">
                  <span>Executor: <strong className="font-mono text-medha-secondary">{config.executor_mode}</strong></span>
                  <span>·</span>
                  <span>Docker CLI: {config.docker_cli ? "Available" : "Missing"}</span>
                  <span>·</span>
                  <span>Database: <strong className="font-mono text-medha-secondary">{config.database_mode}</strong></span>
                </div>
              </>
            )}
          </div>
        </section>

        {/* 5. Appearance & Accessibility */}
        <section aria-labelledby="section-appearance" className="space-y-3">
          <div className="border-b border-medha-border pb-2">
            <h2 id="section-appearance" className="text-[15px] font-semibold text-medha-text">
              Appearance & Accessibility
            </h2>
          </div>

          <div className="rounded-xl border border-medha-border bg-white divide-y divide-medha-border/60 text-[13px]">
            <div className="flex items-center justify-between p-4">
              <div>
                <p className="font-medium text-medha-text">Bright Theme</p>
                <p className="text-[12.5px] text-medha-secondary">
                  Engineered light palette optimized for high information density and daytime readability.
                </p>
              </div>
              <span className="rounded-md border border-medha-border bg-medha-surface-muted px-2 py-0.5 text-[11px] font-medium text-medha-secondary">
                Active
              </span>
            </div>

            <div className="flex items-center justify-between p-4">
              <div>
                <p className="font-medium text-medha-text">Reduce Motion</p>
                <p className="text-[12.5px] text-medha-secondary">
                  Disables smooth scrolling and entrance animations.
                </p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={reduceMotion}
                aria-label="Reduce motion"
                onClick={() => saveMotion(!reduceMotion)}
                className={`relative h-6 w-11 shrink-0 rounded-full transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent ${
                  reduceMotion ? "bg-medha-accent" : "bg-medha-border-strong"
                }`}
              >
                <span
                  className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${
                    reduceMotion ? "left-[22px]" : "left-0.5"
                  }`}
                  aria-hidden
                />
              </button>
            </div>

            <div className="p-4 text-[12px] text-medha-tertiary">
              Keyboard navigation is supported across all workflows with visible focus rings. Operational and security statuses are accompanied by text labels rather than color alone.
            </div>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
