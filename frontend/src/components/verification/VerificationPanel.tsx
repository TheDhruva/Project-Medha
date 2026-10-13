"use client";

import { useDeployment } from "@/context/DeploymentContext";
import { labelStatus, statusGlyph } from "@/lib/ui/status";
import type { CheckStatus } from "@/lib/demo/types";

function checkTone(status: CheckStatus): string {
  switch (status) {
    case "pass":
      return "text-medha-success";
    case "warning":
      return "text-medha-warning";
    case "fail":
      return "text-medha-danger";
    default:
      return "text-medha-tertiary";
  }
}

export function VerificationPanel() {
  const { snapshot, viewMode } = useDeployment();
  const verification = snapshot.verification;
  const critic = snapshot.critic;

  const overall =
    verification == null
      ? null
      : verification.passed === true
        ? "PASS"
        : verification.passed === false
          ? "FAIL"
          : null;

  return (
    <section className="medha-panel animate-medha-in p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
            VERIFICATION
          </h2>
          <p className="mt-1 text-xs text-medha-secondary">
            {verification?.summary ?? "Verification has not started."}
          </p>
        </div>
        {overall ? (
          <span
            className={`rounded-medha-sm px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${
              overall === "PASS"
                ? "bg-medha-success-soft text-medha-success"
                : "bg-medha-danger-soft text-medha-danger"
            }`}
          >
            Overall: {overall}
          </span>
        ) : null}
      </div>

      <ul className="mt-4 grid gap-2 sm:grid-cols-2">
        {(verification?.checks ?? []).map((check) => (
          <li
            key={check.id}
            className="rounded-medha-sm border border-medha-border bg-white px-3 py-2"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-medha-text">{check.name}</span>
              <span className={`text-[11px] font-semibold uppercase ${checkTone(check.status)}`}>
                <span aria-hidden>{statusGlyph(check.status)} </span>
                {labelStatus(check.status)}
              </span>
            </div>
            <p className="mt-1 text-xs text-medha-secondary">{check.message}</p>
            {viewMode === "technical" ? (
              <p className="medha-mono mt-1 text-[10px] text-medha-tertiary">
                check_id={check.id}
                {check.rule ? ` · rule=${check.rule}` : ""}
              </p>
            ) : null}
          </li>
        ))}
      </ul>

      <div className="mt-5 border-t border-medha-border pt-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h3 className="font-display text-sm font-semibold tracking-wide text-medha-text">
              CRITIC SCORE
            </h3>
            <p className="mt-1 text-xs text-medha-secondary">
              Recommendation:{" "}
              <span className="font-semibold text-medha-text">
                {critic && (critic.score > 0 || critic.findings.length > 0)
                  ? critic.recommendation
                  : "Not evaluated yet"}
              </span>
            </p>
          </div>
          <p className="font-display text-3xl font-semibold text-medha-accent">
            {critic && (critic.score > 0 || critic.findings.length > 0) ? `${critic.score}` : "—"}
            <span className="text-base font-medium text-medha-tertiary"> / 100</span>
          </p>
        </div>

        {critic && (critic.score > 0 || critic.findings.length > 0) ? (
          <>
            <dl className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {(
                [
                  ["Security", critic.breakdown.security],
                  ["Completeness", critic.breakdown.completeness],
                  ["Constraints", critic.breakdown.constraints],
                  ["Intent Alignment", critic.breakdown.intentAlignment],
                ] as const
              ).map(([label, value]) => (
                <div
                  key={label}
                  className="rounded-medha-sm border border-medha-border bg-medha-muted/50 px-2.5 py-2"
                >
                  <dt className="text-[10px] uppercase tracking-wide text-medha-tertiary">
                    {label}
                  </dt>
                  <dd className="mt-1 text-sm font-semibold text-medha-text">{value}</dd>
                </div>
              ))}
            </dl>
            {critic.findings.length > 0 ? (
              <ul className="mt-3 space-y-1">
                {critic.findings.map((f) => (
                  <li key={f} className="text-xs leading-relaxed text-medha-secondary">
                    • {f}
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  );
}
