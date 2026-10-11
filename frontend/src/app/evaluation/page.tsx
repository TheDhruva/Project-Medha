"use client";

import type { ReactNode } from "react";
import { useCallback, useEffect, useState, useTransition } from "react";
import { AppShell } from "@/components/layout/AppShell";
import {
  fetchEvaluationSummary,
  runEvaluation,
  type EvaluationSummary,
} from "@/lib/api/client";

export default function EvaluationPage() {
  const [data, setData] = useState<EvaluationSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [pending, startTransition] = useTransition();

  const refresh = useCallback(() => {
    startTransition(async () => {
      try {
        setError(null);
        const summary = await fetchEvaluationSummary();
        setData(summary);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load evaluation");
      } finally {
        setLoaded(true);
      }
    });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const onRun = (kind: "cnp" | "ceg") => {
    startTransition(async () => {
      try {
        setError(null);
        await runEvaluation(kind);
        const summary = await fetchEvaluationSummary();
        setData(summary);
        setLoaded(true);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Evaluation run failed");
      }
    });
  };

  const cnp = data?.cnp as Record<string, unknown> | null | undefined;
  const ceg = data?.ceg as Record<string, unknown> | null | undefined;

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-medha-text">Evaluation</h1>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-medha-secondary">
            What Medha contributes, and how it was measured. Numbers come from
            backend runners — never hardcoded in the UI.
          </p>
        </div>

        <section aria-label="Research contributions" className="rounded-xl border border-medha-border bg-white p-5 sm:p-6">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-medha-tertiary">
            Medha research contributions
          </p>
          <div className="mt-3 space-y-4">
            <Contribution
              title="Constraint Negotiation Protocol"
              simple="When two parts of a deployment want incompatible things, Medha compares their requirements and picks a safe resolution before anything runs."
              technical="Typed constraints with priorities (SECURITY › RESOURCE › DEPENDENCY › PREFERENCE), deterministic resolution within max 3 rounds. See CNP spec."
            />
            <Contribution
              title="Change Impact Graph"
              simple="Medha reads a repository change and maps what else it could affect — files, services, and risk — before deployment."
              technical="Static dependency traversal (direct + transitive) with evidence per edge, risk factors, and verification requirements. No LLM."
            />
            <Contribution
              title="Causal Execution Graph"
              simple="During deployment, Medha records what ran and what depends on what, so failures can be traced."
              technical="Every meaningful execution action becomes a node with parents and reversible actions."
            />
            <Contribution
              title="Evidence-based verification"
              simple="Nothing deploys until independent safety checks pass, and the evidence stays attached to the decision."
              technical="Hard verification gate plus a structured critic score with findings. Failed gates block the executor."
            />
            <Contribution
              title="Dependency-aware rollback"
              simple="If something fails, Medha rolls back only what was actually affected and keeps everything else running."
              technical="Rollback scope is computed from CEG causal edges in reverse order; independent successes are preserved."
            />
          </div>
        </section>

        <section aria-label="Measured results" className="rounded-xl border border-medha-border bg-white p-5 sm:p-6">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-medha-tertiary">
            Measured results
          </p>
          <p className="mt-1 text-sm text-medha-secondary">
            Project-defined evaluation. Empty panels mean artifacts have not been
            generated yet.
          </p>

          {error ? (
            <p
              role="alert"
              className="mt-3 rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-sm text-medha-danger"
            >
              {error}
            </p>
          ) : null}

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={pending}
              onClick={() => onRun("cnp")}
              aria-busy={pending}
              className="rounded-lg bg-medha-accent px-3 py-2 text-sm font-semibold text-white disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
            >
              Run CNP evaluation
            </button>
            <button
              type="button"
              disabled={pending}
              onClick={() => onRun("ceg")}
              aria-busy={pending}
              className="rounded-lg border border-medha-border bg-white px-3 py-2 text-sm font-semibold text-medha-text disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
            >
              Run CEG evaluation
            </button>
            <button
              type="button"
              disabled={pending}
              onClick={refresh}
              className="rounded-lg border border-medha-border bg-white px-3 py-2 text-sm font-medium text-medha-secondary disabled:opacity-60"
            >
              Refresh
            </button>
          </div>

          {!loaded || pending ? (
            <p className="mt-3 text-sm text-medha-secondary" aria-live="polite">
              Loading evaluation results…
            </p>
          ) : null}

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Panel title="CNP" subtitle="Constraint Negotiation Protocol · project-defined">
            {cnp ? (
              <>
                <dl className="space-y-2 text-sm">
                  <Row label="Cases" value={String(cnp.total_cases ?? "—")} />
                  <Row label="Passed" value={String(cnp.passed ?? "—")} />
                  <Row label="Failed" value={String(cnp.failed ?? "—")} />
                  <Row label="Conflicts detected" value={String(cnp.conflicts_detected ?? "—")} />
                  <Row label="Conflicts resolved" value={String(cnp.conflicts_resolved ?? "—")} />
                  <Row label="Avg rounds" value={String(cnp.average_rounds ?? "—")} />
                  <Row
                    label="Resolution rate"
                    value={
                      cnp.conflict_resolution_rate == null
                        ? "n/a (zero denominator)"
                        : String(cnp.conflict_resolution_rate)
                    }
                  />
                </dl>
                <p className="mt-3 text-xs leading-relaxed text-medha-tertiary">
                  Seeded CNP cases only. Passing here means the protocol matched expected outcomes
                  on this dataset — not that all real-world conflicts are solved.
                </p>
              </>
            ) : (
              <p className="text-sm text-medha-secondary">
                No evaluation runs available. Click “Run CNP evaluation” or use{" "}
                <span className="medha-mono text-[11px]">python -m app.evaluation.run_cnp</span>.
              </p>
            )}
          </Panel>
          <Panel title="CEG / Rollback" subtitle="Causal Execution Graph · project-defined">
            {ceg ? (
              <>
                <dl className="space-y-2 text-sm">
                  <Row label="Cases" value={String(ceg.total_cases ?? "—")} />
                  <Row label="Passed" value={String(ceg.passed ?? "—")} />
                  <Row label="Failed" value={String(ceg.failed ?? "—")} />
                  <Row
                    label="MEDHA rollback nodes"
                    value={String(ceg.medha_rollback_nodes_total ?? "—")}
                  />
                  <Row
                    label="Global baseline nodes"
                    value={String(ceg.global_rollback_nodes_total ?? "—")}
                  />
                  <Row label="Preserved nodes" value={String(ceg.preserved_nodes_total ?? "—")} />
                  <Row
                    label="Mean scope efficiency"
                    value={
                      ceg.mean_scope_efficiency == null
                        ? "—"
                        : String(ceg.mean_scope_efficiency)
                    }
                  />
                </dl>
                <p className="mt-3 text-xs leading-relaxed text-medha-tertiary">
                  {String(ceg.total_cases ?? "—")} CEG scenarios evaluated. On these fixtures,
                  MEDHA scoped rollback affected fewer nodes than the global rollback baseline.
                  Scope efficiency is project-defined — not an established academic metric.
                </p>
              </>
            ) : (
              <p className="text-sm text-medha-secondary">
                No evaluation runs available. Click “Run CEG evaluation” or use{" "}
                <span className="medha-mono text-[11px]">python -m app.evaluation.run_ceg</span>.
              </p>
            )}
          </Panel>
        </div>

        <p className="mt-6 text-xs text-medha-tertiary">{data?.note}</p>
        {data?.commands ? (
          <pre className="medha-mono mt-3 overflow-x-auto rounded-xl border border-medha-border bg-white p-3 text-[11px] text-medha-secondary">
            {Object.entries(data.commands)
              .map(([k, v]) => `${k}: ${v}`)
              .join("\n")}
          </pre>
        ) : null}
        </section>
      </div>
    </AppShell>
  );
}

function Contribution({
  title,
  simple,
  technical,
}: {
  title: string;
  simple: string;
  technical: string;
}) {
  return (
    <div className="border-l-2 border-medha-border pl-4">
      <h3 className="text-[15px] font-semibold text-medha-text">{title}</h3>
      <p className="mt-1 text-sm leading-relaxed text-medha-text">{simple}</p>
      <p className="mt-1 text-xs leading-relaxed text-medha-secondary">{technical}</p>
    </div>
  );
}

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-medha-border bg-medha-muted/40 p-4">
      <h2 className="text-sm font-semibold text-medha-text">{title}</h2>
      {subtitle ? <p className="mt-1 text-[11px] text-medha-tertiary">{subtitle}</p> : null}
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-medha-secondary">{label}</dt>
      <dd className="font-semibold text-medha-text">{value}</dd>
    </div>
  );
}
