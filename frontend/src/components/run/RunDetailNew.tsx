"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, CheckCircle2, XCircle, AlertTriangle, Loader2, ChevronDown } from "lucide-react";
import { ChangeImpactPanel } from "@/components/changeintel/ChangeImpactPanel";
import { ConstraintNegotiation } from "@/components/constraints/ConstraintNegotiation";
import { CausalExecutionGraph } from "@/components/graph/CausalExecutionGraph";
import { AgentActivity } from "@/components/agents/AgentActivity";
import { Pipeline } from "@/components/pipeline/Pipeline";
import { VerificationPanel } from "@/components/verification/VerificationPanel";
import { LiveSystemTrace } from "@/components/trace/LiveSystemTrace";
import { WhatMedhaIsDoing } from "@/components/explainability/WhatMedhaIsDoing";
import { ViewModeToggle } from "@/components/explainability/ViewModeToggle";
import { Header } from "@/components/layout/Header";
import { DeploymentProvider, useDeployment } from "@/context/DeploymentContext";
import { scenarioById } from "@/lib/demo/scenarios";
import type { DeploymentSnapshot } from "@/lib/demo/types";
import {
  DecisionCard,
  JourneyCard,
  SummaryRow,
  CollapsibleShell,
  SectionShell,
} from "@/components/run-detail/Cards";
import { EnvBadge } from "@/components/ui/Section";
import { cn } from "@/lib/ui/cn";

function runTitle(snapshot: DeploymentSnapshot, deploymentId: string): string {
  if (snapshot.scenario) {
    try {
      return scenarioById(snapshot.scenario).name;
    } catch {
      /* fall through */
    }
  }
  if (snapshot.changeIntel?.label) return snapshot.changeIntel.label;
  return "Verification run";
}

function StatusLine({ snapshot }: { snapshot: DeploymentSnapshot }) {
  const s = snapshot.runStatus;
  if (s === "succeeded")
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-medha-success">
        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> Completed
      </span>
    );
  if (s === "partial_recovery")
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-medha-warning">
        <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> Recovered
      </span>
    );
  if (s === "failed")
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-medha-danger">
        <XCircle className="h-3.5 w-3.5" aria-hidden /> Blocked
      </span>
    );
  if (s === "running")
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-medha-accent">
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> Running
      </span>
    );
  return <span className="text-xs text-medha-tertiary">Not started</span>;
}

function getEvidenceBullets(snapshot: DeploymentSnapshot): string[] {
  const bullets: string[] = [];
  const checks = snapshot.verification?.checks ?? [];
  if (snapshot.verification?.passed === true && checks.length > 0) {
    const passed = checks.filter((c) => c.status === "pass").length;
    bullets.push(`All required verification checks passed (${passed} / ${checks.length}).`);
  } else if (snapshot.verification?.passed === false) {
    const failed = checks.filter((c) => c.status === "fail");
    if (failed.length > 0) {
      bullets.push(
        `${failed.length} blocking check${failed.length === 1 ? "" : "s"} failed: ${failed.map((f) => f.name).join(", ")}.`,
      );
    } else if (snapshot.verification.summary) {
      bullets.push(snapshot.verification.summary);
    }
  }
  const neg = snapshot.negotiation;
  if (neg?.status === "resolved" && neg.resolution) {
    bullets.push(`Conflict resolved before execution (${neg.resolution}).`);
  } else if (neg?.status === "resolved" && snapshot.constraints.length > 0) {
    bullets.push("Constraints agreed before execution.");
  }
  if (snapshot.critic && (snapshot.critic.score > 0 || snapshot.critic.findings.length > 0)) {
    bullets.push(
      `Independent review scored ${snapshot.critic.score} / 100 (${snapshot.critic.recommendation}).`,
    );
  }
  if (snapshot.rollback) {
    bullets.push(
      `Scoped rollback preserved ${snapshot.rollback.preserved} service${snapshot.rollback.preserved === 1 ? "" : "s"}.`,
    );
  }
  const securityCheck = checks.find((c) => c.id === "security" || c.name.toLowerCase().includes("security"));
  if (securityCheck?.status === "pass" && !bullets.some((b) => b.includes("verification checks passed"))) {
    bullets.push("Security checks passed.");
  }
  return bullets;
}

function EvidenceBullets({ snapshot }: { snapshot: DeploymentSnapshot }) {
  const bullets = getEvidenceBullets(snapshot);
  if (bullets.length === 0) return null;
  return (
    <ul className="space-y-1.5">
      {bullets.map((b) => (
        <li key={b} className="flex items-start gap-2 text-sm leading-relaxed text-medha-text">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-medha-success" aria-hidden />
          <span>{b}</span>
        </li>
      ))}
    </ul>
  );
}

function RunStory({ snapshot }: { snapshot: DeploymentSnapshot }) {
  const { viewMode } = useDeployment();
  const evidenceRef = useRef<HTMLDivElement>(null);
  const recoveryRef = useRef<HTMLDivElement>(null);
  const [changeOpen, setChangeOpen] = useState(false);

  const hasChangeIntel = snapshot.changeIntel != null;
  const hasNegotiation = snapshot.negotiation != null || snapshot.constraints.length > 0;
  const conflictRelevant =
    hasNegotiation &&
    (snapshot.negotiation?.status === "resolving" ||
      snapshot.negotiation?.status === "resolved" ||
      snapshot.constraints.some((c) => c.status !== "accepted"));
  const hasVerification = snapshot.verification != null;
  const checks = snapshot.verification?.checks ?? [];
  const passedChecks = checks.filter((c) => c.status === "pass").length;
  const hasGraph = snapshot.graph.nodes.length > 0;
  const hasRollback = snapshot.rollback != null;
  const failedNodes = snapshot.graph.nodes.filter(
    (n) => n.status === "failed" || n.status === "rolled_back",
  );
  const showRecovery =
    hasRollback || snapshot.runStatus === "partial_recovery" || failedNodes.length > 0;
  const showCeg = hasGraph;
  const technical = viewMode === "technical";

  const scrollTo = (ref: React.RefObject<HTMLDivElement | null>) => {
    ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const changeIntel = snapshot.changeIntel;
  const fileCount = changeIntel?.changeset.files.length ?? 0;
  const affectedCount = changeIntel
    ? new Set([
        ...changeIntel.traversal.direct_targets,
        ...changeIntel.traversal.transitive_targets,
      ]).size
    : 0;

  return (
    <div className="space-y-4">
      <DecisionCard
        snapshot={snapshot}
        onViewEvidence={() => scrollTo(evidenceRef)}
        onViewRecovery={() => scrollTo(recoveryRef)}
      />
      <SummaryRow snapshot={snapshot} />
      <JourneyCard snapshot={snapshot} />

      {/* WHAT CHANGED — only when analysis exists */}
      {hasChangeIntel && changeIntel ? (
        <SectionShell eyebrow="What changed" title="What changed">
          <p className="text-sm text-medha-secondary">
            {fileCount} file{fileCount === 1 ? "" : "s"} changed
            {affectedCount > 0
              ? ` · ${affectedCount} service${affectedCount === 1 ? "" : "s"} potentially affected`
              : ""}
            {changeIntel.risk.level !== "none" ? ` · risk ${changeIntel.risk.level}` : ""}
          </p>
          <ul className="mt-2 space-y-1">
            {changeIntel.changeset.files.slice(0, 5).map((f) => (
              <li key={f.path} className="medha-mono text-xs text-medha-text">
                {f.path}{" "}
                <span className="text-medha-tertiary">
                  +{f.added_lines}/−{f.deleted_lines}
                </span>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => setChangeOpen((v) => !v)}
            aria-expanded={changeOpen}
            className="mt-3 text-sm font-medium text-medha-accent hover:underline"
          >
            {changeOpen ? "Hide change impact ↑" : "View change impact →"}
          </button>
          {changeOpen ? (
            <div className="mt-3">
              <p className="mb-2 text-[11px] uppercase tracking-wide text-medha-tertiary">
                Change impact · CIG — Change Impact Graph
              </p>
              <ChangeImpactPanel analysis={changeIntel} />
            </div>
          ) : null}
        </SectionShell>
      ) : null}

      {/* CONFLICT RESOLUTION — only when relevant */}
      {conflictRelevant && snapshot.negotiation ? (
        <CollapsibleShell
          eyebrow="Conflict resolution · CNP — Constraint Negotiation Protocol"
          title="Conflict resolution"
          preview={
            snapshot.negotiation.status === "resolved"
              ? "Resolved before deployment"
              : "A conflict needs attention"
          }
          actionLabel="See how Medha resolved it"
        >
          <ConstraintNegotiation />
        </CollapsibleShell>
      ) : null}

      {/* SAFETY VERIFICATION — only when verification data exists */}
      {hasVerification ? (
        <CollapsibleShell
          eyebrow="Safety verification"
          title={
            checks.length > 0
              ? `${passedChecks} / ${checks.length} checks passed`
              : "Safety verification"
          }
          preview={
            snapshot.verification?.passed === true
              ? "No blocking issues detected."
              : snapshot.verification?.passed === false
                ? "A blocking issue was found."
                : "Verification has not finished."
          }
          actionLabel="View checks"
        >
          <VerificationPanel />
        </CollapsibleShell>
      ) : null}

      {/* EVIDENCE */}
      <div ref={evidenceRef} className="scroll-mt-20">
        <SectionShell eyebrow="Evidence" title="Why was this decision made?">
          {getEvidenceBullets(snapshot).length > 0 ? (
            <EvidenceBullets snapshot={snapshot} />
          ) : (
            <p className="text-sm text-medha-secondary">
              Evidence is not available for this run yet.
            </p>
          )}
          <CollapsibleShell
            eyebrow="Supporting artifacts"
            title="View evidence"
            preview="Stored verification results and findings"
          >
            {hasVerification ? (
              <VerificationPanel />
            ) : (
              <p className="text-sm text-medha-secondary">
                Verification artifacts are not available for this run.
              </p>
            )}
          </CollapsibleShell>
        </SectionShell>
      </div>

      {/* RECOVERY — only when execution data exists */}
      {showRecovery ? (
        <div ref={recoveryRef} className="scroll-mt-20">
          <SectionShell
            eyebrow="Deployment recovery · CEG — Causal Execution Graph"
            title="Deployment recovery"
          >
            {snapshot.rollback ? (
              <>
                <p className="text-sm leading-relaxed text-medha-text">
                  {snapshot.rollback.simpleExplanation}
                </p>
                <p className="mt-2 text-sm text-medha-secondary">
                  {snapshot.rollback.rolledBack} rolled back · {snapshot.rollback.preserved}{" "}
                  preserved · {snapshot.rollback.failed} failed
                </p>
              </>
            ) : (
              <p className="text-sm text-medha-secondary">
                Execution data is available below. Rollback details appear here when a
                scoped recovery occurs.
              </p>
            )}
            {showCeg ? (
              <div className="mt-3">
                <CausalExecutionGraph />
              </div>
            ) : null}
          </SectionShell>
        </div>
      ) : null}

      {/* TECHNICAL DETAILS — collapsed by default in Simple mode */}
      <TechnicalDetails snapshot={snapshot} />
    </div>
  );
}

function TechnicalDetails({ snapshot }: { snapshot: DeploymentSnapshot }) {
  const { viewMode } = useDeployment();
  const technical = viewMode === "technical";
  const [open, setOpen] = useState(technical);
  useEffect(() => {
    setOpen(technical);
  }, [technical]);

  const hasChangeIntel = snapshot.changeIntel != null;
  const hasNegotiation = snapshot.negotiation != null || snapshot.constraints.length > 0;
  const hasVerification = snapshot.verification != null;
  const hasGraph = snapshot.graph.nodes.length > 0;

  return (
    <section
      aria-label="Technical details"
      className="overflow-hidden rounded-xl border border-medha-border bg-white"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left transition hover:bg-medha-muted/50"
      >
        <span>
          <span className="block text-[11px] font-semibold uppercase tracking-[0.1em] text-medha-tertiary">
            Technical details
          </span>
          <span className="mt-0.5 block text-[15px] font-semibold text-medha-text">
            Internal pipeline, graphs, agents, and event timeline
          </span>
          {!open ? (
            <span className="mt-0.5 block text-[13px] text-medha-secondary">
              {snapshot.isDemo ? "Deterministic demo fixture." : "Real backend data."} Expand for
              expert inspection.
            </span>
          ) : null}
        </span>
        <span className="flex shrink-0 items-center gap-3">
          <ViewModeToggle />
          <ChevronDown
            className={cn("h-4 w-4 text-medha-secondary transition-transform", open && "rotate-180")}
            aria-hidden
          />
        </span>
      </button>
      {open ? (
        <div className="space-y-4 border-t border-medha-border px-5 py-4">
          <WhatMedhaIsDoing />
          <Pipeline />
          {/* CNP details live here for experts even when the simple summary hid them */}
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-medha-tertiary">
              Conflict resolution detail · CNP
            </p>
            {hasNegotiation ? (
              <ConstraintNegotiation />
            ) : (
              <p className="text-sm text-medha-secondary">
                No constraint negotiation data for this run.
              </p>
            )}
          </div>
          {hasVerification || technical ? (
            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-medha-tertiary">
                Verification detail
              </p>
              <VerificationPanel />
            </div>
          ) : null}
          {hasChangeIntel ? (
            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-medha-tertiary">
                Change impact graph · CIG
              </p>
              <ChangeImpactPanel analysis={snapshot.changeIntel} />
            </div>
          ) : null}
          {hasGraph || technical ? (
            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-medha-tertiary">
                Execution graph · CEG
              </p>
              <CausalExecutionGraph />
            </div>
          ) : null}
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-medha-tertiary">
              System activity · 10 specialized agents
            </p>
            <AgentActivity />
          </div>
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-medha-tertiary">
              Event timeline
            </p>
            <LiveSystemTrace />
          </div>
        </div>
      ) : null}
    </section>
  );
}

function RunBody({ deploymentId }: { deploymentId: string }) {
  const { snapshot, openDeployment, hydrating, connectionError } = useDeployment();
  const isHydratedFor = snapshot.deploymentId === deploymentId;
  const failedToLoad =
    isHydratedFor &&
    !hydrating &&
    snapshot.runStatus === "failed" &&
    snapshot.explain.statusLabel === "Failed to load";

  useEffect(() => {
    void openDeployment(deploymentId);
  }, [deploymentId, openDeployment]);

  if (hydrating || !isHydratedFor) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
        <section className="rounded-xl border border-medha-border bg-white p-10 text-center">
          <Loader2 className="mx-auto h-5 w-5 animate-spin text-medha-accent" aria-hidden />
          <p className="mt-3 text-[15px] font-semibold text-medha-text">
            Loading verification run…
          </p>
          <p className="mt-1 text-sm text-medha-secondary" aria-live="polite">
            Fetching the decision, evidence, and history.
          </p>
        </section>
      </main>
    );
  }

  if (failedToLoad) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
        <section
          role="alert"
          className="rounded-xl border border-medha-border bg-white p-10 text-center"
        >
          <p className="text-[15px] font-semibold text-medha-text">Unable to load this run.</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-medha-secondary">
            {connectionError || "This run could not be found."}
          </p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <button
              type="button"
              onClick={() => void openDeployment(deploymentId)}
              className="rounded-lg bg-medha-accent px-4 py-2 text-sm font-semibold text-white hover:bg-medha-accent-hover"
            >
              Retry
            </button>
            <Link
              href="/runs"
              className="rounded-lg border border-medha-border bg-white px-4 py-2 text-sm font-medium text-medha-text hover:bg-medha-muted"
            >
              Back to runs
            </Link>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl space-y-4 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link
          href="/runs"
          className="inline-flex items-center gap-1 text-sm text-medha-secondary hover:text-medha-text"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Runs
        </Link>
        <div className="flex items-center gap-2">
          <EnvBadge isDemo={snapshot.isDemo} size="sm" />
          <button
            type="button"
            onClick={() => void openDeployment(deploymentId)}
            className="rounded-lg border border-medha-border bg-white px-3 py-1.5 text-xs font-medium text-medha-secondary hover:bg-medha-muted"
          >
            Reload
          </button>
        </div>
      </div>

      <div>
        <h1 className="text-2xl font-bold tracking-tight text-medha-text">
          {runTitle(snapshot, deploymentId)}
        </h1>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
          <StatusLine snapshot={snapshot} />
          <span className="medha-mono truncate text-[11px] text-medha-tertiary">
            {deploymentId}
          </span>
        </div>
      </div>

      {connectionError ? (
        <p
          role="status"
          className="rounded-xl border border-medha-warning/30 bg-medha-warning-soft px-4 py-2.5 text-[13px] text-medha-warning"
        >
          Live updates disconnected. Showing the last saved state.
        </p>
      ) : null}

      <RunStory snapshot={snapshot} />
    </main>
  );
}

export function RunDetailView({ deploymentId }: { deploymentId: string }) {
  return (
    <DeploymentProvider>
      <div className={cn("min-h-screen bg-medha-bg")}>
        <Header />
        <RunBody deploymentId={deploymentId} />
      </div>
    </DeploymentProvider>
  );
}
