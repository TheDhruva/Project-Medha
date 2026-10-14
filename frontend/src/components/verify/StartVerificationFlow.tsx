"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
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
import {
  createProjectRun,
  fetchConfigStatus,
  fetchProject,
  type ExecutionReadiness,
  type Project,
} from "@/lib/api/client";
import { cn } from "@/lib/ui/cn";

const FULL_SHA = /^[0-9a-fA-F]{40}$/;

function Flow() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const projectId = searchParams.get("project");
  const { form, setForm, startDeployment, isRunning, snapshot, connectionError } =
    useDeployment();
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [startedId, setStartedId] = useState<string | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<ExecutionReadiness | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // This flow only starts real repository analyses. The deterministic demo
  // engine is not part of the product workflow, so the form always runs in
  // real mode regardless of the context default.
  useEffect(() => {
    setForm({ mode: "real" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Project mode: the repository is locked to the project's stored identity.
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    fetchProject(projectId)
      .then((value) => {
        if (!cancelled) {
          setProject(value);
          setProjectError(null);
        }
      })
      .catch(() => {
        if (!cancelled) setProjectError("Project could not be loaded — check the link or backend.");
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Execution readiness: warn honestly when the execute stage cannot run.
  useEffect(() => {
    let cancelled = false;
    fetchConfigStatus()
      .then((status) => {
        if (!cancelled) setReadiness(status?.execution_readiness ?? null);
      })
      .catch(() => {
        if (!cancelled) setReadiness(null);
      });
    return () => {
      cancelled = true;
    };
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

  const busy = isRunning || submitting;

  function analyzeGit() {
    setFormError(null);
    // Both endpoints require exact 40-hex SHAs (or omitted); fail early with
    // an actionable message instead of a backend 422/400.
    const base = form.baseRevision.trim();
    const target = form.targetRevision.trim();
    if (base && !FULL_SHA.test(base)) {
      setFormError(
        "Base revision must be a full 40-character commit SHA (for example the output of git rev-parse HEAD).",
      );
      return;
    }
    if (target && !FULL_SHA.test(target)) {
      setFormError(
        "Target revision must be a full 40-character commit SHA (for example the output of git rev-parse HEAD).",
      );
      return;
    }
    if (projectId) {
      const portRaw = form.targetPort.trim();
      const port = portRaw ? Number.parseInt(portRaw, 10) : null;
      if (portRaw && (port == null || !Number.isFinite(port) || port < 1 || port > 65535)) {
        setFormError("Target port must be a number between 1 and 65535.");
        return;
      }
      const host = form.targetHost.trim();
      setSubmitting(true);
      createProjectRun(projectId, {
        intent: form.intent.trim() || undefined,
        base_revision: base || undefined,
        target_revision: target || undefined,
        ...(host ? { target_host: host } : {}),
        ...(port != null ? { target_port: port } : {}),
      })
        .then((response) => {
          router.push(`/projects/${projectId}/runs/${response.deployment_id}`);
        })
        .catch((err) => {
          setFormError(
            err instanceof Error
              ? err.message
              : "Cannot reach MEDHA backend. Is the API service running?",
          );
        })
        .finally(() => setSubmitting(false));
      return;
    }
    // Repository URL + revisions ride the real-mode deployment request:
    // revisions scope change-impact analysis for local git repositories.
    startDeployment();
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-8 sm:px-6 bg-medha-surface min-h-screen">
      <button
        type="button"
        onClick={() => router.push(projectId ? `/projects/${projectId}` : "/projects")}
        className="inline-flex items-center gap-1 text-sm text-medha-secondary hover:text-medha-text mb-4"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Back to {projectId ? "project" : "projects"}
      </button>

      <h1 className="mt-3 text-2xl font-bold tracking-tight text-medha-text">
        New analysis
      </h1>
      <p className="mt-1 text-sm text-medha-secondary">
        {projectId
          ? "Analyze a change in this project's repository. Nothing executes before verification passes and required approvals are granted."
          : "Analyze a real repository change. Nothing executes before verification passes and required approvals are granted."}
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
            value={projectId ? (project ? project.repository : "") : form.repositoryUrl}
            onChange={(e) => setForm({ repositoryUrl: e.target.value})}
            placeholder={
              projectId
                ? project
                  ? ""
                  : "Loading project repository…"
                : "https://github.com/org/repo or local path"
            }
            readOnly={Boolean(projectId)}
            disabled={busy}
          />
          {projectId ? (
            <p className="mt-1 text-[10.5px] text-medha-tertiary">
              Locked to this project&apos;s configured repository.
              {projectError ? ` ${projectError}` : ""}
            </p>
          ) : null}
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
              placeholder="40-hex SHA (optional)"
              disabled={busy}
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
              placeholder="40-hex SHA (optional)"
              disabled={busy}
            />
          </div>
        </div>
        <p className="mt-2 text-[10px] text-medha-tertiary">
          {projectId
            ? "Revisions are optional full commit SHAs. Omit both to run a full analysis of the project's current HEAD."
            : "Change analysis runs against the repository you provide. For local git repositories, revisions scope the change-impact diff; otherwise the deployment proceeds without change-intel."}
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
                    disabled={busy}
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
                    disabled={busy}
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
                  disabled={busy}
                />
              </div>
            </div>
          ) : null}
        </div>

        {readiness && readiness.status !== "ready" ? (
          <p role="status" className="mt-3 rounded-md border border-medha-warning/30 bg-medha-warning-soft px-3 py-2 text-xs text-medha-warning">
            Execution stage currently unavailable ({readiness.reason_code}) — {readiness.message}
            {" "}Analysis and verification will still run and their results stay valid.
          </p>
        ) : null}

        {connectionError ? (
          <p role="alert" className="mt-3 rounded-md border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-xs text-medha-danger">
            {connectionError}
          </p>
        ) : null}
        {formError ? (
          <p role="alert" className="mt-3 rounded-md border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-xs text-medha-danger">
            {formError}
          </p>
        ) : null}
        <div className="mt-4 flex items-center gap-2">
          <button
            type="button"
            onClick={analyzeGit}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-md bg-medha-accent px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-medha-accent-hover disabled:opacity-60"
          >
            {busy ? (
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
