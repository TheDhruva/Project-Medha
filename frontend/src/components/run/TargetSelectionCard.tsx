"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { GitFork, Loader2 } from "lucide-react";
import type { DeploymentSnapshot, TargetCandidateView } from "@/lib/demo/types";
import { cn } from "@/lib/ui/cn";

/** Result codes that mean "pick one deployment target, then retry". */
const TARGET_CODES = new Set([
  "MULTIPLE_APPS_REQUIRE_TARGET",
  "INVALID_DEPLOYMENT_TARGET",
  "AMBIGUOUS_DEPLOY_TARGET",
]);

/**
 * Actionable target picker for runs blocked on application selection.
 * Candidates come from the run's own persisted result; project targets are
 * the fallback when the run predates candidate detail. Saving persists to
 * project settings AND passes the explicit target to the retry run, so the
 * retry cannot silently lose the selection.
 */
export function TargetSelectionCard({
  snapshot,
  deploymentId,
  projectId,
}: {
  snapshot: DeploymentSnapshot;
  deploymentId: string;
  projectId?: string;
}) {
  const router = useRouter();
  const code =
    typeof snapshot.result?.code === "string" ? snapshot.result.code : null;
  const analysis = snapshot.result?.repository_analysis ?? null;
  const isCanonical = (projectId ?? "").startsWith("prj_");
  const [fallback, setFallback] = useState<{
    candidates: TargetCandidateView[];
    deployTarget: string | null;
    note: string | null;
  } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fromResult = snapshot.result?.target_selection;
  const candidates: TargetCandidateView[] =
    (fromResult?.candidates ?? []).length > 0
      ? (fromResult?.candidates ?? [])
      : (fallback?.candidates ?? []);
  const activeTarget =
    fromResult?.selected_target ?? fallback?.deployTarget ?? null;

  useEffect(() => {
    if (!isCanonical || !projectId) return;
    if ((fromResult?.candidates ?? []).length > 0) return;
    let cancelled = false;
    void (async () => {
      try {
        const { fetchProjectTargets } = await import("@/lib/api/client");
        const t = await fetchProjectTargets(projectId);
        if (!cancelled) {
          setFallback({
            candidates: t.candidates ?? [],
            deployTarget: t.deploy_target ?? null,
            note: t.note ?? null,
          });
        }
      } catch {
        if (!cancelled) setFallback(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isCanonical, projectId, fromResult]);

  if (snapshot.runStatus !== "failed" || !code || !TARGET_CODES.has(code)) {
    return null;
  }

  const chosen = (selected ?? activeTarget ?? "").trim();

  async function saveAndRetry() {
    if (!projectId || !chosen || saving) return;
    setSaving(true);
    setError(null);
    try {
      const { updateProject, createProjectRun } = await import(
        "@/lib/api/client"
      );
      await updateProject(projectId, { deploy_target: chosen });
      const response = await createProjectRun(projectId, {
        deployment_target: chosen,
      });
      router.push(`/projects/${projectId}/runs/${response.deployment_id}`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not save the target.",
      );
      setSaving(false);
    }
  }

  return (
    <section
      aria-label="Deployment target required"
      className="rounded-xl border border-medha-danger/25 bg-white p-5 sm:p-6"
    >
      <p className="medha-label">
        Action needed
      </p>
      <h2 className="mt-1 text-lg font-semibold tracking-tight text-medha-text">
        Choose one application to deploy
      </h2>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-medha-secondary">
        {snapshot.result?.message ??
          "This repository contains multiple applications. V1 deploys exactly one service per run."}
      </p>
      {analysis ? (
        <div className="mt-3 rounded-lg border border-medha-border bg-medha-muted/40 p-3">
          <p className="medha-label">
            Repository analysis
          </p>
          <p className="mt-1 text-[13px] text-medha-secondary">
            Analysis {analysis.analysis_status ?? "completed"} across{" "}
            {analysis.applications?.length ?? 0} application
            {(analysis.applications?.length ?? 0) === 1 ? "" : "s"}. Only the
            deployment is blocked, on the target choice above.
          </p>
          {analysis.languages?.length ? (
            <p className="medha-mono mt-1 break-all text-[12.5px] leading-5 text-medha-secondary">
              Languages: {analysis.languages.map((l) => l.language).join(", ")}
            </p>
          ) : null}
          {analysis.coverage?.gaps?.length ? (
            <ul className="mt-1 list-disc pl-4 text-[12.5px] leading-5 text-medha-secondary">
              {analysis.coverage.gaps.slice(0, 4).map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {candidates.length > 0 ? (
        <ul className="mt-3 space-y-2">
          {candidates.map((c) => {
            const active = chosen === c.path;
            return (
              <li key={c.path}>
                <button
                  type="button"
                  onClick={() => setSelected(c.path)}
                  aria-pressed={active}
                  className={cn(
                    "flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition",
                    active
                      ? "border-medha-accent bg-medha-accent/5"
                      : "border-medha-border bg-white hover:bg-medha-muted/60",
                  )}
                >
                  <GitFork
                    className="mt-0.5 h-4 w-4 shrink-0 text-medha-secondary"
                    aria-hidden
                  />
                  <span className="min-w-0">
                    <span className="medha-mono block truncate text-[13px] font-semibold text-medha-text">
                      {c.path}
                      {activeTarget === c.path && !selected ? (
                        <span className="ml-2 rounded bg-medha-muted px-1.5 py-0.5 text-[12.5px] font-medium text-medha-secondary">
                          saved target
                        </span>
                      ) : null}
                    </span>
                    {c.technologies.length > 0 ? (
                      <span className="mt-0.5 block text-[12px] text-medha-secondary">
                        {c.technologies.join(" · ")}
                      </span>
                    ) : null}
                    {c.evidence.length > 0 ? (
                      <span className="medha-mono mt-0.5 block break-all text-[12px] leading-4 text-medha-secondary">
                        {c.evidence.slice(0, 3).join(", ")}
                      </span>
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-3 text-[13px] text-medha-secondary">
          No candidate list was recorded for this run.{" "}
          {isCanonical ? (
            <>
              Set the target in{" "}
              <Link
                href={`/projects/${projectId}/settings`}
                className="font-semibold text-medha-accent hover:underline"
              >
                project settings
              </Link>{" "}
              (use the repository-relative directory, e.g. backend), then retry.
            </>
          ) : (
            "Re-run the analysis to refresh the candidate list."
          )}
        </p>
      )}
      {isCanonical && candidates.length > 0 ? (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void saveAndRetry()}
            disabled={!chosen || saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-medha-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : null}
            {saving ? "Starting…" : "Save target & retry"}
          </button>
          <Link
            href={`/projects/${projectId}/settings`}
            className="rounded-lg border border-medha-border bg-white px-4 py-2 text-sm font-medium text-medha-text hover:bg-medha-muted"
          >
            Project settings
          </Link>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="mt-2 text-[12.5px] text-medha-danger">
          {error}
        </p>
      ) : null}
      <p className="mt-2 text-[12.5px] leading-5 text-medha-tertiary">
        Run {deploymentId.slice(0, 12)}… stays unchanged; the retry is a new
        run with this target.
        {!isCanonical ? (
          <>
            {" "}This run is not bound to a project —{" "}
            <Link href="/projects" className="font-medium text-medha-accent hover:underline">
              connect the repository as a project
            </Link>{" "}
            to select a target and retry.
          </>
        ) : null}
      </p>
    </section>
  );
}
