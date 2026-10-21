"use client";

import { useEffect, useState } from "react";
import { fetchScores, type ProductScore } from "@/lib/api/client";

const SCORE_META: { key: string; title: string; blurb: string }[] = [
  { key: "code_quality", title: "Code quality", blurb: "Static analysis and build/test evidence that actually ran for this run." },
  { key: "security", title: "Security posture", blurb: "Scanner results and container security config. Missing scans are unassessed, never clean." },
  { key: "verification_confidence", title: "Verification confidence", blurb: "Required verification checks passed, warned, or failed." },
  { key: "deployment_readiness", title: "Deployment readiness", blurb: "Target support, verification, execution and recorded health evidence." },
  { key: "performance", title: "Performance", blurb: "Static risk estimate. Benchmarks appear only when actually measured." },
  { key: "optimization", title: "Optimization", blurb: "Higher means better optimized (fewer open opportunities)." },
];

type EvidenceCheck = {
  id?: string;
  title?: string;
  status?: string;
  severity?: string;
  finding?: string;
  evidence_source?: string;
  reference?: string | null;
  score_impact?: number;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function evidenceChecks(score: ProductScore): EvidenceCheck[] {
  const raw = asRecord(score.evidence)?.checks;
  return Array.isArray(raw)
    ? raw
        .map(asRecord)
        .filter((c): c is Record<string, unknown> => c !== null)
        .map((c) => ({
          id: typeof c.id === "string" ? c.id : undefined,
          title: typeof c.title === "string" ? c.title : undefined,
          status: typeof c.status === "string" ? c.status : undefined,
          severity: typeof c.severity === "string" ? c.severity : undefined,
          finding: typeof c.finding === "string" ? c.finding : undefined,
          evidence_source: typeof c.evidence_source === "string" ? c.evidence_source : undefined,
          reference: typeof c.reference === "string" ? c.reference : null,
          score_impact: typeof c.score_impact === "number" ? c.score_impact : undefined,
        }))
    : [];
}

const STATUS_STYLE: Record<string, string> = {
  passed: "text-medha-success-ink",
  warning: "text-medha-warning",
  failed: "text-medha-danger",
  not_assessed: "text-medha-tertiary",
  skipped: "text-medha-tertiary",
  not_applicable: "text-medha-tertiary",
};

function ScoreCard({ title, blurb, score }: { title: string; blurb: string; score?: ProductScore }) {
  if (!score) {
    return (
      <div className="rounded-lg border border-medha-border bg-white px-3.5 py-3">
        <p className="text-[14.5px] font-semibold leading-5 text-medha-text">{title}</p>
        <p className="mt-0.5 text-[13px] font-medium text-medha-tertiary">Not measured</p>
        <p className="mt-1 text-[12.5px] leading-4 text-medha-secondary">{blurb}</p>
      </div>
    );
  }
  const ev = asRecord(score.evidence) ?? {};
  const coverage = asRecord(ev.coverage);
  const checks = evidenceChecks(score);
  const relevant = checks.filter((c) => c.status !== "passed" || c.severity === "critical" || c.severity === "high");
  const top = typeof ev.top_finding === "string" ? ev.top_finding : null;
  const reason = typeof ev.reason === "string" ? ev.reason : null;
  return (
    <div className="rounded-lg border border-medha-border bg-white px-3.5 py-3">
      <p className="text-[14.5px] font-semibold leading-5 text-medha-text">{title}</p>
      {score.value == null ? (
        <p className="mt-0.5 text-[13px] font-medium text-medha-tertiary">Not assessed</p>
      ) : (
        <p className="mt-0.5 text-[24px] font-semibold leading-none text-medha-text">{Math.round(score.value)}<span className="text-[13px] font-normal text-medha-tertiary"> / 100</span></p>
      )}
      {top ? <p className="mt-1 text-[13px] leading-5 text-medha-secondary">{top}</p> : null}
      {score.value == null && reason ? (
        <p className="mt-1 text-[12.5px] leading-5 text-medha-secondary">Reason: {reason}</p>
      ) : null}
      {coverage && typeof coverage.assessed === "number" && typeof coverage.applicable === "number" ? (
        <p className="mt-1 text-[12px] leading-4 text-medha-secondary">Coverage: {coverage.assessed}/{coverage.applicable} applicable checks assessed</p>
      ) : null}
      <p className="mt-0.5 break-words text-[12px] leading-4 text-medha-tertiary">
        {score.version} · {score.computed_at.slice(0, 19).replace("T", " ")} · inputs {score.inputs_hash.slice(0, 12)}
        {score.target_sha ? ` · revision ${score.target_sha.slice(0, 8)}` : ""}
      </p>
      <p className="mt-1 text-[12.5px] leading-4 text-medha-secondary">{blurb}</p>
      {relevant.length > 0 ? (
        <details className="mt-1.5">
          <summary className="cursor-pointer text-[12.5px] font-semibold text-medha-accent">
            Find {relevant.length} check{relevant.length === 1 ? "" : "s"} affecting this score
          </summary>
          <ul className="mt-1 space-y-1">
            {relevant.map((c, i) => (
              <li key={`${c.id ?? i}`} className="rounded border border-medha-border px-2 py-1.5 text-[12.5px]">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className={`font-semibold ${STATUS_STYLE[c.status ?? ""] ?? "text-medha-tertiary"}`}>
                    {(c.status ?? "unknown").replace(/_/g, " ")}
                  </span>
                  <span className="font-medium text-medha-text">{c.title ?? c.id ?? "check"}</span>
                  {c.severity ? <span className="text-medha-tertiary">· {c.severity}</span> : null}
                  {c.score_impact ? <span className="text-medha-tertiary">· −{c.score_impact} pts</span> : null}
                </div>
                {c.finding ? <p className="text-medha-secondary">{c.finding}</p> : null}
                <p className="text-[12px] leading-4 text-medha-tertiary">
                  {c.evidence_source ?? "unknown source"}{c.reference ? ` · ${c.reference}` : ""}
                </p>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

export function ScoresPanel({ runId }: { runId: string }) {
  const [scores, setScores] = useState<Record<string, ProductScore> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchScores(runId)
      .then((res) => {
        if (!cancelled) setScores(res.scores);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Scores unavailable.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  if (loading) {
    return <p className="text-[13.5px] text-medha-secondary">Computing evidence-backed scores…</p>;
  }
  if (error) {
    return (
      <p className="text-[13px] text-medha-secondary">
        Scores unavailable: {error}
      </p>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {SCORE_META.map((m) => (
        <ScoreCard key={m.key} title={m.title} blurb={m.blurb} score={scores?.[m.key]} />
      ))}
    </div>
  );
}
