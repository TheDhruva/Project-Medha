"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  GitBranch,
  ChevronDown,
  ArrowRight,
  ArrowLeft,
  Loader2,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import {
  DeploymentProvider,
  useDeployment,
} from "@/context/DeploymentContext";
import { cn } from "@/lib/ui/cn";

function Flow() {
  const router = useRouter();
  const { form, setForm, startDeployment, isRunning, snapshot, connectionError } =
    useDeployment();
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [startedId, setStartedId] = useState<string | null>(null);

  // This flow only starts real repository analyses. The deterministic demo
  // engine is not part of the product workflow, so the form always runs in
  // real mode regardless of the context default.
  useEffect(() => {
    setForm({ mode: "real" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // After a deployment starts, follow it to its run page once we know the id.
  const deploymentId = snapshot.deploymentId;
  useEffect(() => {
    if (
      deploymentId &&
      deploymentId !== startedId &&
      (snapshot.runStatus === "running" ||
        snapshot.runStatus === "succeeded" ||
        snapshot.runStatus === "failed" ||
        snapshot.runStatus === "partial_recovery")
    ) {
      setStartedId(deploymentId);
      router.push(`/runs/${deploymentId}`);
    }
  }, [deploymentId, snapshot.runStatus, startedId, router]);

  function analyzeGit() {
    // Repository URL + revisions ride the real-mode deployment request:
    // revisions scope change-impact analysis for local git repositories.
    startDeployment();
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-8 sm:px-6 bg-medha-surface min-h-screen">
      <button
        type="button"
        onClick={() => router.push("/projects")}
        className="inline-flex items-center gap-1 text-sm text-medha-secondary hover:text-medha-text mb-4"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Back to projects
      </button>

      <h1 className="mt-3 text-2xl font-bold tracking-tight text-medha-text">
        New analysis
      </h1>
      <p className="mt-1 text-sm text-medha-secondary">
        Analyze a real repository change. Nothing executes before verification
        passes and required approvals are granted.
      </p>

      <section aria-label="Repository change" className="mt-6 rounded-md border border-medha-border bg-medha-surface p-5">
        <p className="flex items-center gap-2 text-[14px] font-semibold text-medha-text">
          <GitBranch className="h-4 w-4 text-medha-accent" aria-hidden />
          Repository change
        </p>
        <div className="mt-3">
          <label htmlFor="git-repo" className="medha-label block">
            Repository
          </label>
          <input
            id="git-repo"
            className="field-input mt-1.5"
            value={form.repositoryUrl}
            onChange={(e) => setForm({ repositoryUrl: e.target.value})}
            placeholder="https://github.com/org/repo or local path"
            disabled={isRunning}
          />
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="git-base" className="medha-label block">
              Base revision
            </label>
            <input
              id="git-base"
              className="field-input mt-1.5"
              value={form.baseRevision}
              onChange={(e) => setForm({ baseRevision: e.target.value})}
              placeholder="e.g. main or abc1234"
              disabled={isRunning}
            />
          </div>
          <div>
            <label htmlFor="git-target" className="medha-label block">
              Target revision
            </label>
            <input
              id="git-target"
              className="field-input mt-1.5"
              value={form.targetRevision}
              onChange={(e) => setForm({ targetRevision: e.target.value})}
              placeholder="e.g. HEAD"
              disabled={isRunning}
            />
          </div>
        </div>
        <p className="mt-2 text-[10px] text-medha-tertiary">
          Change analysis runs against the repository you provide. For local git
          repositories, revisions scope the change-impact diff; otherwise the
          deployment proceeds without change-intel.
        </p>

        <div className="mt-4 border-t border-medha-border pt-3">
          <button
            type="button"
            onClick={() => setAdvancedOpen((v) => !v)}
            aria-expanded={advancedOpen}
            className="inline-flex items-center gap-1 text-sm font-medium text-medha-secondary hover:text-medha-text"
          >
            Advanced options
            <ChevronDown
              className={cn("h-3.5 w-3.5 transition-transform", advancedOpen && "rotate-180")}
              aria-hidden
            />
          </button>
          {advancedOpen ? (
            <div className="mt-3 space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="adv-host" className="medha-label block">
                    Target host
                  </label>
                  <input
                    id="adv-host"
                    className="field-input mt-1.5"
                    value={form.targetHost}
                    onChange={(e) => setForm({ targetHost: e.target.value})}
                    disabled={isRunning}
                  />
                </div>
                <div>
                  <label htmlFor="adv-port" className="medha-label block">
                    Target port
                  </label>
                  <input
                    id="adv-port"
                    className="field-input mt-1.5"
                    inputMode="numeric"
                    value={form.targetPort}
                    onChange={(e) => setForm({ targetPort: e.target.value})}
                    disabled={isRunning}
                  />
                </div>
              </div>
              <div>
                <label htmlFor="adv-intent" className="medha-label block">
                  Deployment intent
                </label>
                <input
                  id="adv-intent"
                  className="field-input mt-1.5"
                  value={form.intent}
                  onChange={(e) => setForm({ intent: e.target.value})}
                  disabled={isRunning}
                />
              </div>
            </div>
          ) : null}
        </div>

        {connectionError ? (
          <p role="alert" className="mt-3 rounded-md border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-xs text-medha-danger">
            {connectionError}
          </p>
        ) : null}
        <div className="mt-4 flex items-center gap-2">
          <button
            type="button"
            onClick={analyzeGit}
            disabled={isRunning}
            className="inline-flex items-center gap-2 rounded-md bg-medha-accent px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-medha-accent-hover disabled:opacity-60"
          >
            {isRunning ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> Analyzing…
              </>
            ) : (
              <>
                Analyze change <ArrowRight className="h-3.5 w-3.5" aria-hidden />
              </>
            )}
          </button>
        </div>
      </section>
    </main>
  );
}

export function StartVerificationFlow() {
  return (
    <DeploymentProvider>
      <AppShell>
        <Flow />
      </AppShell>
    </DeploymentProvider>
  );
}
