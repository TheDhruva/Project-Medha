"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchScores, type ProductScore } from "@/lib/api/client";
import { scoreTone } from "@/lib/projects/metrics";
import { Badge, Panel } from "@/components/ui/primitives";
import { cn } from "@/lib/ui/cn";

/* Verification scores, two panels side by side on wide screens:
   a compact clickable summary (left) and the actionable findings behind
   low scores (right). Backed by stored scoring evidence (backend
   `scores-v4`): 100 minus each failed/warning check's documented
   score_impact, then capped. A check that never ran is incompleteness —
   never a defect, never a pass. Every sentence derives from the stored
   evidence; when the reason is not recorded, the panel says so instead
   of guessing. */

interface ScoreFinding {
  severity?: string;
  rule_id?: string;
  path?: string;
  line?: number | string | null;
  message?: string;
}

interface ScoreCheck {
  id?: string;
  title?: string;
  status?: string;
  severity?: string;
  finding?: string;
  evidence_source?: string;
  reference?: string | null;
  score_impact?: number;
  findings?: ScoreFinding[];
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function evidenceChecks(score: ProductScore): ScoreCheck[] {
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
          findings: Array.isArray(c.findings)
            ? c.findings
                .map(asRecord)
                .filter((f): f is Record<string, unknown> => f !== null)
                .map((f) => ({
                  severity: typeof f.severity === "string" ? f.severity : undefined,
                  rule_id: typeof f.rule_id === "string" ? f.rule_id : undefined,
                  path: typeof f.path === "string" ? f.path : undefined,
                  line: typeof f.line === "number" || typeof f.line === "string" ? f.line : null,
                  message: typeof f.message === "string" ? f.message : undefined,
                }))
            : [],
        }))
    : [];
}

/* Plain-English text for the documented score caps and unassessed reasons
   the backend records (see backend/app/scores/compute.py). Unknown values
   fall back to the recorded backend text — never an invented explanation. */
const CAP_TEXT: Record<string, string> = {
  secret_finding: "A secret (like a password or key) was found in the code.",
  critical_security: "A critical security problem was found.",
  high_security: "A serious security problem was found.",
  critical_code: "A serious code problem was found.",
  verification_failed: "Verification did not pass, so readiness cannot go above 40.",
  unhealthy: "The application was reported unhealthy.",
  unsupported_target: "This deployment target is not supported.",
  missing_health: "App health was not checked, so readiness cannot go above 75.",
  missing_execution: "The app was not really executed, so readiness cannot go above 60.",
  simulated_execution: "This run used a simulation, which is not real deployment evidence.",
  critical_blocker: "A critical blocker was found.",
  no_security_scanner: "The security scan has not finished, so the score cannot go above 60.",
  partial_security_scanner: "Some security scans did not finish, so the score cannot go above 85.",
  no_static_analysis: "The code check has not run, so the score cannot go above 80.",
};

const REASON_TEXT: Record<string, string> = {
  "no code-quality check produced evidence for this run": "No code check produced evidence for this run.",
  "no security scanner completed; security coverage is unknown": "The security scan has not finished.",
  "no required verification check actually ran": "No required verification check actually ran.",
  "no verification checks were recorded for this run": "No verification checks were recorded.",
  "no deployment-readiness check produced evidence": "No deployment-readiness evidence was recorded.",
  "no applicable check produced evidence": "No check produced evidence for this run.",
};

/* How a finding should be labelled: a confirmed problem in the repository,
   an unfinished analysis, or a completed pass. Kept to a small, consistent
   vocabulary so beginners can trust the colors. */
const KIND_TEXT = {
  code: { label: "Code issue", badge: "error" as const },
  security: { label: "Security issue", badge: "error" as const },
  fail: { label: "Failed check", badge: "error" as const },
  missing: { label: "Check not run", badge: "warning" as const },
  incomplete: { label: "Check incomplete", badge: "warning" as const },
  risk: { label: "Recorded risk", badge: "warning" as const },
  passed: { label: "Passed", badge: "success" as const },
};

type FindingKind = keyof typeof KIND_TEXT;

interface CategoryFinding {
  kind: FindingKind;
  title: string;
  points?: number;
  files?: ScoreFinding[];
  source?: string;
  reference?: string | null;
}

const VALUE_TEXT: Record<string, string> = {
  success: "text-medha-success-ink",
  warning: "text-medha-warning",
  danger: "text-medha-danger",
  neutral: "text-medha-tertiary",
};

/* Which documented cap triggers mean "the analysis never ran" vs "a real
   problem was confirmed". Mirrors backend/app/scores/compute.py CAPS. */
const CAP_KIND: Record<string, FindingKind> = {
  secret_finding: "security",
  critical_security: "security",
  high_security: "security",
  critical_code: "code",
  critical_blocker: "fail",
  verification_failed: "fail",
  unhealthy: "fail",
  unsupported_target: "fail",
  no_security_scanner: "missing",
  no_static_analysis: "missing",
  partial_security_scanner: "incomplete",
  simulated_execution: "incomplete",
  missing_health: "incomplete",
  missing_execution: "incomplete",
};

const CATEGORIES = [
  { key: "code_quality", title: "Code quality", coverageText: "completed", kind: "code" },
  { key: "security", title: "Security", coverageText: "completed", kind: "security" },
  { key: "verification_confidence", title: "Verification", coverageText: "passed", kind: "fail" },
  { key: "deployment_readiness", title: "Deployment readiness", coverageText: "passed", kind: "fail" },
] as const;

function coverageLine(
  score: ProductScore | undefined,
  coverageText: "completed" | "passed",
): string | null {
  const coverage = asRecord(asRecord(score?.evidence)?.coverage);
  if (
    !coverage ||
    typeof coverage.assessed !== "number" ||
    typeof coverage.applicable !== "number" ||
    typeof coverage.passed !== "number"
  ) {
    return null;
  }
  return coverageText === "passed"
    ? `${coverage.passed}/${coverage.applicable} checks passed`
    : `${coverage.assessed}/${coverage.applicable} checks completed`;
}

function categoryFindings(
  score: ProductScore | undefined,
  fallbackKind: FindingKind,
): CategoryFinding[] {
  if (!score) return [];
  const ev = asRecord(score.evidence) ?? {};
  const checks = evidenceChecks(score);
  const caps = Array.isArray(ev.caps_applied)
    ? ev.caps_applied.map(asRecord).filter((c): c is Record<string, unknown> => c !== null)
    : [];
  const reason = typeof ev.reason === "string" ? ev.reason : null;
  const out: CategoryFinding[] = [];

  if (score.value == null) {
    out.push({
      kind: "missing",
      title: reason ? (REASON_TEXT[reason] ?? reason) : "No evidence was recorded for this run.",
    });
    return out;
  }

  for (const cap of caps) {
    const trigger = typeof cap.trigger === "string" ? cap.trigger : "";
    out.push({
      kind: CAP_KIND[trigger] ?? "risk",
      title: CAP_TEXT[trigger] ?? (typeof cap.reason === "string" ? cap.reason : "A recorded risk caps this score."),
    });
  }
  for (const c of checks) {
    if ((c.status === "failed" || c.status === "warning") && (c.score_impact ?? 0) > 0) {
      out.push({
        kind: fallbackKind,
        title: c.finding?.trim() || c.title || "Check recorded an issue.",
        points: c.score_impact,
        files: c.findings?.filter((f) => f.path) ?? [],
        source: c.evidence_source,
        reference: c.reference,
      });
    }
  }
  if (out.length === 0) {
    const coverage = asRecord(ev.coverage);
    const clean =
      coverage &&
      typeof coverage.assessed === "number" &&
      typeof coverage.failed === "number" &&
      typeof coverage.warnings === "number" &&
      coverage.assessed > 0 &&
      coverage.failed === 0 &&
      coverage.warnings === 0;
    out.push({
      kind: "passed",
      title: clean
        ? "All completed checks passed."
        : "The exact reason for this score is not recorded with the evidence.",
    });
  }
  return out;
}

function ScoreRow({
  title,
  score,
  coverageText,
  href,
}: {
  title: string;
  score: ProductScore | undefined;
  coverageText: "completed" | "passed";
  href: string;
}) {
  const coverage = coverageLine(score, coverageText);
  return (
    <Link
      href={href}
      className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 py-2.5 transition-colors hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
    >
      <span className="text-[14px] font-semibold text-medha-text">
        {title} ·{" "}
        {score?.value == null ? (
          <span className="text-medha-tertiary">{score ? "Not assessed" : "Not measured"}</span>
        ) : (
          <span className={VALUE_TEXT[scoreTone(score.value)]}>{Math.round(score.value)}/100</span>
        )}
      </span>
      {coverage ? (
        <span className="ml-auto shrink-0 text-[12.5px] text-medha-tertiary">{coverage}</span>
      ) : null}
    </Link>
  );
}

function FindingRow({
  category,
  finding,
  runHref,
}: {
  category: string;
  finding: CategoryFinding;
  runHref: string;
}) {
  const kind = KIND_TEXT[finding.kind];
  const showActionLink = finding.kind === "missing" || finding.kind === "incomplete";
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Badge tone={kind.badge}>{kind.label}</Badge>
        <span className="min-w-0 text-[13.5px] font-medium text-medha-text">{finding.title}</span>
        {finding.points ? (
          <span className="shrink-0 text-[12.5px] text-medha-tertiary">−{finding.points} points</span>
        ) : null}
      </p>
      <p className="mt-1 text-[12.5px] text-medha-tertiary">
        {category}
        {finding.kind === "missing" || finding.kind === "incomplete"
          ? " · This lowers confidence in the score until the analysis is finished."
          : finding.points
            ? " · This is a confirmed problem that reduced the score."
            : null}
      </p>
      {(finding.files ?? []).length > 0 ? (
        <ul className="mt-1 space-y-0.5">
          {finding.files?.map((f, i) => (
            <li key={i} className="text-[12.5px] leading-4 text-medha-secondary">
              <span className="medha-mono text-medha-tertiary">
                {f.path}
                {f.line != null ? `:${f.line}` : ""}
              </span>
              {f.message ? ` — ${f.message}` : null}
            </li>
          ))}
          <li className="text-[12.5px] leading-4 text-medha-tertiary">
            Fix: review the file above and address these findings.
          </li>
        </ul>
      ) : null}
      {finding.source ? (
        <details className="mt-1">
          <summary className="cursor-pointer rounded text-[12.5px] font-semibold text-medha-accent transition-colors hover:text-medha-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">
            Supporting evidence
          </summary>
          <p className="mt-1 text-[12px] leading-4 text-medha-tertiary">
            {finding.source}
            {finding.reference ? ` · ${finding.reference}` : ""}
          </p>
        </details>
      ) : null}
      {showActionLink ? (
        <Link
          href={runHref}
          className="mt-1 inline-block rounded text-[12.5px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
        >
          Open run details →
        </Link>
      ) : null}
    </li>
  );
}

export function ScoresPanel({ projectId, runId }: { projectId: string; runId: string }) {
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

  const runHref = `/projects/${projectId}/runs/${runId}`;
  const findings = CATEGORIES.flatMap((cat) =>
    categoryFindings(scores?.[cat.key], cat.kind).map((f) => ({
      category: cat.title,
      finding: f,
    })),
  );

  return (
    <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
      <Panel title="Your scores">
        {loading ? (
          <p className="text-[13.5px] text-medha-secondary">Loading scores…</p>
        ) : error ? (
          <p className="text-[13px] text-medha-secondary">Scores are unavailable: {error}</p>
        ) : (
          <div className="divide-y divide-medha-border">
            {CATEGORIES.map((cat) => (
              <ScoreRow
                key={cat.key}
                title={cat.title}
                score={scores?.[cat.key]}
                coverageText={cat.coverageText}
                href={
                  cat.key === "deployment_readiness"
                    ? runHref
                    : "#findings"
                }
              />
            ))}
          </div>
        )}
      </Panel>
      <Panel id="findings" title="Findings">
        {loading ? (
          <p className="text-[13.5px] text-medha-secondary">Loading findings…</p>
        ) : error ? (
          <p className="text-[13px] text-medha-secondary">Findings are unavailable: {error}</p>
        ) : findings.length > 0 ? (
          <ul className="divide-y divide-medha-border">
            {findings.map(({ category, finding }, i) => (
              <FindingRow key={`${category}-${i}`} category={category} finding={finding} runHref={runHref} />
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-medha-secondary">
            No score evidence was stored for this run.
          </p>
        )}
      </Panel>
    </div>
  );
}
