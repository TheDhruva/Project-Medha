"use client";

import { useDeployment } from "@/context/DeploymentContext";
import { labelStatus, statusGlyph } from "@/lib/ui/status";
import type { CheckStatus } from "@/lib/demo/types";
import { cn } from "@/lib/ui/cn";

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

/**
 * Consolidated verification + critic: compact outcome by default
 * (status, passed/total, blocking findings, critic score), full check and
 * artifact evidence behind disclosures or in Technical mode. A PASS here
 * gates execution — it never claims a healthy deployment.
 */
export function VerificationPanel() {
  const { snapshot, viewMode } = useDeployment();
  const verification = snapshot.verification;
  const critic = snapshot.critic;
  const technical = viewMode === "technical";

  const checks = verification?.checks ?? [];
  const passed = checks.filter((c) => c.status === "pass").length;
  const blocking = checks.filter((c) => c.status === "fail");
  const warnings = checks.filter((c) => c.status === "warning");
  const criticReady = critic != null && (critic.score > 0 || critic.findings.length > 0);

  const overall =
    verification == null
      ? null
      : verification.passed === true
        ? "PASS"
        : verification.passed === false
          ? "FAIL"
          : null;

  return (
    <section className="medha-panel animate-medha-in p-4" aria-label="Verification and critic review">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
            VERIFICATION
          </h2>
          <p className="mt-1 text-[13px] text-medha-secondary">
            {checks.length > 0 ? (
              <>{passed} / {checks.length} checks passed{blocking.length > 0 ? <> · <span className="font-semibold text-medha-danger">{blocking.length} blocking</span></> : null}{warnings.length > 0 ? ` · ${warnings.length} warning${warnings.length === 1 ? "" : "s"}` : ""}</>
            ) : (
              verification?.summary ?? "Verification has not started."
            )}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {criticReady ? (
            <span className="rounded-medha-sm border border-medha-border bg-white px-2 py-1 text-[11px] text-medha-secondary" title="Independent critic review — not a deployment health claim">
              Critic <span className="font-bold text-medha-text">{critic.score}</span>/100 · {critic.recommendation}
            </span>
          ) : null}
          {overall ? (
            <span
              className={cn(
                "rounded-medha-sm px-2 py-1 text-[11px] font-semibold uppercase tracking-wide",
                overall === "PASS"
                  ? "bg-medha-success-soft text-medha-success"
                  : "bg-medha-danger-soft text-medha-danger",
              )}
            >
              {overall}
            </span>
          ) : null}
        </div>
      </div>

      {blocking.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {blocking.slice(0, 3).map((c) => (
            <li key={c.id} className="rounded-medha-sm border border-medha-danger/25 bg-medha-danger-soft px-2.5 py-1.5 text-[12.5px] text-medha-danger">
              <span className="font-semibold">{c.name}.</span> {c.message}
            </li>
          ))}
        </ul>
      ) : null}

      {(checks.length > 0 || criticReady) && (technical || blocking.length > 0 || !overall) ? (
        <details className="mt-2" open={technical}>
          <summary className="cursor-pointer text-[12.5px] font-semibold text-medha-accent">
            Inspect evidence ({checks.length} checks{criticReady ? " + critic" : ""})
          </summary>
          <ul className="mt-1.5 space-y-1">
            {checks.map((check) => (
              <li key={check.id} className="rounded-medha-sm border border-medha-border bg-white px-2.5 py-1.5">
                <p className="flex flex-wrap items-center gap-x-2 text-[12.5px]">
                  <span className={cn("text-[11px] font-semibold uppercase", checkTone(check.status))}>
                    <span aria-hidden>{statusGlyph(check.status)} </span>
                    {labelStatus(check.status)}
                  </span>
                  <span className="font-medium text-medha-text">{check.name}</span>
                </p>
                {check.message ? <p className="mt-0.5 text-[12px] text-medha-secondary">{check.message}</p> : null}
                {technical ? (
                  <p className="medha-mono mt-0.5 text-[10.5px] text-medha-tertiary">
                    check_id={check.id}{check.rule ? ` · rule=${check.rule}` : ""}{check.category ? ` · ${check.category}` : ""}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
          {criticReady ? (
            <div className="mt-1.5 rounded-medha-sm border border-medha-border bg-white px-2.5 py-1.5">
              <p className="text-[12.5px] text-medha-secondary">
                Critic <span className="font-bold text-medha-text">{critic.score}/100</span> · {critic.recommendation}
                {" · "}security {critic.breakdown.security} · completeness {critic.breakdown.completeness} · constraints {critic.breakdown.constraints} · intent {critic.breakdown.intentAlignment}
              </p>
              {critic.findings.length > 0 ? (
                <ul className="mt-1 list-inside list-disc space-y-0.5 text-[12px] text-medha-secondary">
                  {critic.findings.map((f) => <li key={f}>{f}</li>)}
                </ul>
              ) : null}
            </div>
          ) : null}
        </details>
      ) : null}
    </section>
  );
}
