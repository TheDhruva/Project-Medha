"use client";

import { useEffect, useState } from "react";
import { fetchScores, type ProductScore } from "@/lib/api/client";

const SCORE_META: { key: string; title: string; blurb: string }[] = [
  { key: "deployment_readiness", title: "Deployment readiness", blurb: "Evidence of build/config/health-check fitness. High readiness does not mean deployed." },
  { key: "performance", title: "Performance", blurb: "Static risk estimate. Benchmarks appear only when actually measured." },
  { key: "optimization", title: "Optimization", blurb: "Higher means better optimized (fewer open opportunities)." },
  { key: "security", title: "Security", blurb: "Findings, severity, and scan coverage. Missing coverage caps the score." },
];

function ScoreCard({ title, blurb, score }: { title: string; blurb: string; score?: ProductScore }) {
  if (!score) {
    return (
      <div className="rounded-lg border border-medha-border bg-white px-3 py-2.5">
        <p className="text-[13px] font-semibold text-medha-text">{title}</p>
        <p className="mt-0.5 text-[13px] font-medium text-medha-tertiary">Not measured</p>
        <p className="mt-0.5 text-[12px] text-medha-tertiary">{blurb}</p>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-medha-border bg-white px-3 py-2.5">
      <p className="text-[13px] font-semibold text-medha-text">{title}</p>
      {score.value == null ? (
        <p className="mt-0.5 text-[13px] font-medium text-medha-tertiary">Insufficient evidence</p>
      ) : (
        <p className="mt-0.5 text-[18px] font-bold text-medha-text">{Math.round(score.value)}<span className="text-[12px] font-normal text-medha-tertiary"> / 100</span></p>
      )}
      <p className="mt-0.5 text-[11px] text-medha-tertiary">
        {score.version} · {score.computed_at.slice(0, 19).replace("T", " ")} · inputs {score.inputs_hash.slice(0, 12)}
      </p>
      <p className="mt-0.5 text-[12px] text-medha-tertiary">{blurb}</p>
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
    return <p className="text-[13px] text-medha-secondary">Computing evidence-backed scores…</p>;
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
