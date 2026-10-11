"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  FlaskConical,
  GitBranch,
  ChevronDown,
  ArrowRight,
  ArrowLeft,
  Loader2,
} from "lucide-react";
import { Header } from "@/components/layout/Header";
import {
  DeploymentProvider,
  useDeployment,
} from "@/context/DeploymentContext";
import { SCENARIOS } from "@/lib/demo/scenarios";
import type { ScenarioId } from "@/lib/demo/types";
import { cn } from "@/lib/ui/cn";

type Choice = "demo" | "git" | null;

function Flow() {
  const router = useRouter();
  const { form, setForm, startDeployment, isRunning, snapshot, connectionError } =
    useDeployment();
  const [choice, setChoice] = useState<Choice>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [startedId, setStartedId] = useState<string | null>(null);

  const selectedScenario = SCENARIOS.find((s) => s.id === form.scenario);

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

  function chooseDemo() {
    setChoice("demo");
    setForm({ mode: "demo" });
  }

  function chooseGit() {
    setChoice("git");
    setForm({ mode: "real" });
  }

  function continueDemo() {
    startDeployment();
  }

  function analyzeGit() {
    // Repository URL + revisions ride the real-mode deployment request:
    // revisions scope change-impact analysis for local git repositories.
    startDeployment();
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-8 sm:px-6">
      <button
        type="button"
        onClick={() => (choice ? setChoice(null) : router.push("/"))}
        className="inline-flex items-center gap-1 text-sm text-medha-secondary hover:text-medha-text"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Back
      </button>

      <h1 className="mt-3 text-2xl font-bold tracking-tight text-medha-text">
        What would you like to verify?
      </h1>
      <p className="mt-1 text-sm text-medha-secondary">
        Choose a deterministic demo scenario, or analyze a real repository change.
      </p>

      {choice === null ? (
        <div className="mt-6 grid gap-3 sm:grid-cols-2">
          <button
            type="button"
            onClick={chooseDemo}
            className="rounded-xl border border-medha-border bg-white p-5 text-left transition hover:border-medha-accent/40 hover:shadow-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
          >
            <FlaskConical className="h-5 w-5 text-medha-accent" aria-hidden />
            <span className="mt-3 block text-[15px] font-semibold text-medha-text">
              Demo scenario
            </span>
            <span className="mt-1 block text-[13px] leading-relaxed text-medha-secondary">
              Explore Medha using a deterministic scenario.
            </span>
          </button>
          <button
            type="button"
            onClick={chooseGit}
            className="rounded-xl border border-medha-border bg-white p-5 text-left transition hover:border-medha-accent/40 hover:shadow-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
          >
            <GitBranch className="h-5 w-5 text-medha-accent" aria-hidden />
            <span className="mt-3 block text-[15px] font-semibold text-medha-text">
              Git change
            </span>
            <span className="mt-1 block text-[13px] leading-relaxed text-medha-secondary">
              Analyze a real repository change.
            </span>
          </button>
        </div>
      ) : null}

      {choice === "demo" ? (
        <section aria-label="Demo scenario" className="mt-6 rounded-xl border border-medha-border bg-white p-5">
          <h2 className="text-[15px] font-semibold text-medha-text">Choose scenario</h2>
          <div className="mt-3 space-y-2" role="radiogroup" aria-label="Demo scenario">
            {SCENARIOS.map((s) => {
              const active = form.scenario === s.id;
              return (
                <button
                  key={s.id}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => setForm({ scenario: s.id as ScenarioId })}
                  disabled={isRunning}
                  className={cn(
                    "w-full rounded-lg border px-4 py-3 text-left transition",
                    active
                      ? "border-medha-accent bg-medha-accent-soft/40"
                      : "border-medha-border hover:border-medha-strong",
                  )}
                >
                  <span className="block text-sm font-semibold text-medha-text">{s.name}</span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-medha-secondary">
                    {s.description}
                  </span>
                </button>
              );
            })}
          </div>
          {selectedScenario ? (
            <p className="mt-3 text-xs text-medha-secondary">
              <span className="font-medium text-medha-text">Expected: </span>
              {selectedScenario.expectedBehavior}
            </p>
          ) : null}
          {connectionError ? (
            <p role="alert" className="mt-3 rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-xs text-medha-danger">
              {connectionError}
            </p>
          ) : null}
          <div className="mt-4 flex items-center gap-2">
            <button
              type="button"
              onClick={continueDemo}
              disabled={isRunning}
              className="inline-flex items-center gap-2 rounded-lg bg-medha-accent px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-medha-accent-hover disabled:opacity-60"
            >
              {isRunning ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Starting…
                </>
              ) : (
                <>
                  Continue <ArrowRight className="h-4 w-4" aria-hidden />
                </>
              )}
            </button>
            <button
              type="button"
              onClick={() => setChoice(null)}
              disabled={isRunning}
              className="text-sm text-medha-secondary hover:text-medha-text"
            >
              Change choice
            </button>
          </div>
        </section>
      ) : null}

      {choice === "git" ? (
        <section aria-label="Git change" className="mt-6 rounded-xl border border-medha-border bg-white p-5">
          <label htmlFor="git-repo" className="medha-label block">
            Repository
          </label>
          <input
            id="git-repo"
            className="field-input mt-1.5"
            value={form.repositoryUrl}
            onChange={(e) => setForm({ repositoryUrl: e.target.value })}
            placeholder="https://github.com/org/repo or local path"
            disabled={isRunning}
          />
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="git-base" className="medha-label block">
                Base revision
              </label>
              <input
                id="git-base"
                className="field-input mt-1.5"
                value={form.baseRevision}
                onChange={(e) => setForm({ baseRevision: e.target.value })}
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
                onChange={(e) => setForm({ targetRevision: e.target.value })}
                placeholder="e.g. HEAD"
                disabled={isRunning}
              />
            </div>
          </div>
          <p className="mt-2 text-[11px] text-medha-tertiary">
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
                className={cn("h-4 w-4 transition-transform", advancedOpen && "rotate-180")}
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
                      onChange={(e) => setForm({ targetHost: e.target.value })}
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
                      onChange={(e) => setForm({ targetPort: e.target.value })}
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
                    onChange={(e) => setForm({ intent: e.target.value })}
                    disabled={isRunning}
                  />
                </div>
              </div>
            ) : null}
          </div>

          {connectionError ? (
            <p role="alert" className="mt-3 rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-xs text-medha-danger">
              {connectionError}
            </p>
          ) : null}
          <div className="mt-4 flex items-center gap-2">
            <button
              type="button"
              onClick={analyzeGit}
              disabled={isRunning}
              className="inline-flex items-center gap-2 rounded-lg bg-medha-accent px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-medha-accent-hover disabled:opacity-60"
            >
              {isRunning ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Analyzing…
                </>
              ) : (
                <>
                  Analyze change <ArrowRight className="h-4 w-4" aria-hidden />
                </>
              )}
            </button>
            <button
              type="button"
              onClick={() => setChoice(null)}
              disabled={isRunning}
              className="text-sm text-medha-secondary hover:text-medha-text"
            >
              Change choice
            </button>
          </div>
        </section>
      ) : null}
    </main>
  );
}

export function StartVerificationFlow() {
  return (
    <DeploymentProvider>
      <div className="min-h-screen bg-medha-bg">
        <Header />
        <Flow />
      </div>
    </DeploymentProvider>
  );
}
