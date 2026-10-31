"use client";

import React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Code2,
  HelpCircle,
  Info,
  MinusCircle,
  Rocket,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Verified,
  X,
  XCircle,
} from "lucide-react";
import type { ScorecardMetric } from "@/lib/projects/metrics";
import { cn } from "@/lib/ui/cn";

interface ScoreExplanationModalProps {
  metric: ScorecardMetric | null;
  onClose: () => void;
  previousValue?: number | null;
}

const SCORE_DEFINITIONS: Record<
  ScorecardMetric["id"],
  {
    whatItMeans: string;
    howEvaluated: string;
    improvementTips: string[];
    whatCouldBeMissing: string;
  }
> = {
  "code-quality": {
    whatItMeans:
      "Code Quality reflects the maintainability, structural clarity, and static health of your codebase.",
    howEvaluated:
      "Evaluates syntax and static-analysis findings, complexity indicators, framework conventions, and directory organization.",
    improvementTips: [
      "Address flagged code complexity or lint warnings in application files.",
      "Ensure consistent naming, modular file organization, and clean imports.",
      "Add documentation or docstrings to public exported functions.",
    ],
    whatCouldBeMissing:
      "If a language-specific linter or static analyzer was not configured for your project, some structural risks may remain unassessed.",
  },
  security: {
    whatItMeans:
      "Security Posture reflects the presence or absence of vulnerabilities, exposed credentials, and risky configurations.",
    howEvaluated:
      "Evaluates static security analysis (e.g. Semgrep), secret leaks (e.g. Gitleaks), and vulnerable third-party dependencies.",
    improvementTips: [
      "Rotate any credentials, API tokens, or private keys immediately if flagged.",
      "Update vulnerable dependencies with known security advisories in your lockfile.",
      "Remove permissive CORS, debug endpoints, or hardcoded secrets.",
    ],
    whatCouldBeMissing:
      "Static scanning cannot detect all runtime, logic, or zero-day vulnerabilities. A high score is not a guarantee of total security.",
  },
  verification: {
    whatItMeans:
      "Verification Confidence measures whether automated tests, build steps, and architectural constraints pass reliably.",
    howEvaluated:
      "Evaluates discovered test suites, build assertions, compose configurations, and port integrity checks.",
    improvementTips: [
      "Add unit and integration tests covering critical business logic.",
      "Ensure tests run reliably without flaky timeouts or network dependencies.",
      "Validate container and environment manifests in your repository.",
    ],
    whatCouldBeMissing:
      "Checks that were skipped or not applicable do not count as verified. Untested execution paths remain unverified.",
  },
  readiness: {
    whatItMeans:
      "Deployment Readiness indicates whether the project can be safely built, containerized, and started in a live environment.",
    howEvaluated:
      "Evaluates build profiles, Dockerfile specifications, container health probes, published port contracts, and runtime prerequisites.",
    improvementTips: [
      "Ensure Docker Desktop or the container runtime daemon is running locally.",
      "Verify container start commands and ensure the application listens on the configured port.",
      "Define standard health-check routes for automated readiness confirmation.",
    ],
    whatCouldBeMissing:
      "If Docker is not running or the project is a standalone library rather than a deployable web app, deployment readiness is marked blocked or not applicable.",
  },
};

export function ScoreExplanationModal({
  metric,
  onClose,
  previousValue,
}: ScoreExplanationModalProps) {
  if (!metric) return null;

  const def = SCORE_DEFINITIONS[metric.id];
  const value = metric.value;
  const isNotAssessed = value == null;
  const isNotApplicable = metric.status === "not_applicable";
  const isBlocked = metric.status === "critical" || metric.status === "partial";

  const diff =
    previousValue != null && value != null ? value - previousValue : null;

  const whatItMeans = isNotApplicable
    ? "Deployment Readiness is not applicable for this repository. MEDHA detected that this codebase is a library, package, or command-line tool without a standalone web service entry point."
    : def.whatItMeans;

  const whatCouldBeMissing = isNotApplicable
    ? "Automated containerization and port probing were intentionally skipped because this repository does not declare a long-running web application."
    : def.whatCouldBeMissing;

  const improvementTips = isNotApplicable
    ? [
        "If this repository contains a web application, add a Dockerfile or compose configuration declaring a target port.",
        "Ensure your application stack defines a runnable entry point in repository manifests.",
      ]
    : def.improvementTips;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-2xs animate-in fade-in duration-150"
      role="dialog"
      aria-modal="true"
      aria-labelledby="score-modal-title"
    >
      <div
        className="w-full max-w-lg rounded-xl border border-medha-border bg-white shadow-xl overflow-hidden max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-medha-border px-5 py-4 bg-medha-surface-soft/60">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-medha-border bg-white shadow-2xs">
              {metric.id === "code-quality" && <Code2 className="h-4 w-4 text-medha-text" />}
              {metric.id === "security" && <ShieldCheck className="h-4 w-4 text-medha-text" />}
              {metric.id === "verification" && <Verified className="h-4 w-4 text-medha-text" />}
              {metric.id === "readiness" && <Rocket className="h-4 w-4 text-medha-text" />}
            </div>
            <div>
              <h2 id="score-modal-title" className="text-[16px] font-semibold text-medha-text">
                {metric.title}
              </h2>
              <p className="text-[12px] text-medha-secondary">{metric.statusLabel}</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <span
              className={cn(
                "font-mono text-[20px] font-semibold",
                value == null
                  ? "text-medha-secondary"
                  : value >= 85
                    ? "text-medha-success"
                    : value >= 60
                      ? "text-medha-warning"
                      : "text-medha-danger",
              )}
            >
              {value != null ? `${value}/100` : "—"}
            </span>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded-md p-1.5 text-medha-secondary hover:bg-medha-surface-muted hover:text-medha-text"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Scrollable Body */}
        <div className="overflow-y-auto p-5 space-y-4 text-[13px] text-medha-text leading-relaxed">
          {/* Historical comparison banner if exists */}
          {diff != null && (
            <div className="flex items-center gap-2 rounded-lg border border-medha-border bg-medha-surface-soft px-3 py-2 text-[12.5px]">
              {diff > 0 ? (
                <>
                  <TrendingUp className="h-4 w-4 text-medha-success" />
                  <span className="font-medium text-medha-success">+{diff} points</span>
                  <span className="text-medha-secondary">compared to previous assessment</span>
                </>
              ) : diff < 0 ? (
                <>
                  <TrendingDown className="h-4 w-4 text-medha-danger" />
                  <span className="font-medium text-medha-danger">{diff} points</span>
                  <span className="text-medha-secondary">compared to previous assessment</span>
                </>
              ) : (
                <span className="text-medha-secondary">Same score as previous assessment</span>
              )}
            </div>
          )}

          {/* 1. What the score means */}
          <div>
            <h3 className="font-semibold text-[13px] text-medha-text uppercase tracking-wide text-medha-secondary text-[11.5px]">
              What this score means
            </h3>
            <p className="mt-1 text-medha-text">{whatItMeans}</p>
          </div>

          {/* 2. Actual factors that affected the score */}
          <div>
            <h3 className="font-semibold text-[11.5px] uppercase tracking-wide text-medha-secondary">
              Scoring factors & evidence
            </h3>
            <div className="mt-1.5 rounded-lg border border-medha-border bg-medha-surface-soft p-3">
              <p className="font-medium text-medha-text">{metric.evidence}</p>
              {metric.coverage ? (
                <p className="mt-1 text-[12px] text-medha-secondary">
                  Completed {metric.coverage.assessed} of {metric.coverage.applicable} applicable checks for this category.
                </p>
              ) : null}
            </div>
          </div>

          {/* 3. What could not be checked */}
          <div>
            <h3 className="font-semibold text-[11.5px] uppercase tracking-wide text-medha-secondary">
              What could not be checked
            </h3>
            <p className="mt-1 text-medha-secondary text-[12.5px]">{whatCouldBeMissing}</p>
          </div>

          {/* 4. How to improve this result */}
          <div>
            <h3 className="font-semibold text-[11.5px] uppercase tracking-wide text-medha-secondary">
              How to improve this score
            </h3>
            <ul className="mt-1.5 space-y-1 text-[12.5px] text-medha-secondary">
              {improvementTips.map((tip, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-medha-accent shrink-0" />
                  <span>{tip}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Footer */}
        <div className="border-t border-medha-border px-5 py-3 flex items-center justify-between bg-medha-surface-soft/40">
          <a
            href={metric.href}
            className="text-[12.5px] font-semibold text-medha-accent hover:underline inline-flex items-center gap-1"
          >
            Inspect technical findings →
          </a>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-medha-border bg-white px-3 py-1.5 text-[12.5px] font-medium text-medha-text hover:bg-medha-surface-muted"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

