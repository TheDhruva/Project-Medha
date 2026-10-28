import type { DeploymentSnapshot } from "@/lib/demo/types";

export type DecisionKind = "approved" | "blocked" | "recovered" | "running" | "awaiting" | "unknown";

export function getDecision(snapshot: DeploymentSnapshot): {
  kind: DecisionKind;
  title: string;
  body: string;
  cta: string;
  score: number | null;
  risk: string | null;
} {
  const { runStatus, result, verification, critic, changeIntel } = snapshot;

  // Real score only: critic with meaningful content, or result score > 0.
  let score: number | null = null;
  if (critic && typeof critic.score === "number") {
    const hasSignal = critic.score > 0 || critic.findings.length > 0;
    if (hasSignal) score = critic.score;
  }
  if (score == null && result?.verificationScore != null && result.verificationScore > 0) {
    score = result.verificationScore;
  }

  const risk = changeIntel?.risk.level && changeIntel.risk.level !== "none"
    ? changeIntel.risk.level
    : null;

  if (runStatus === "running" || runStatus === "idle") {
    return {
      kind: "running",
      title: "Verification in progress",
      body: snapshot.explain.simpleText || "Medha is working through this run.",
      cta: "View progress",
      score: null,
      risk,
    };
  }

  if (runStatus === "partial_recovery") {
    const preserved = snapshot.rollback?.preserved;
    const rolledBack = snapshot.rollback?.rolledBack;
    return {
      kind: "recovered",
      title: "Deployment recovered",
      body:
        snapshot.rollback?.simpleExplanation ||
        result?.message ||
        "Execution partially failed. Affected dependencies were rolled back.",
      cta: "View recovery",
      score,
      risk,
    };
  }

  if (runStatus === "failed") {
    const blockedByVerification = verification?.passed === false;
    // Acquisition/checkout failures never reached deployment at all:
    // "Deployment blocked" would wrongly imply the deployment decision was
    // the issue. Name the real failure instead.
    const code = (result?.code ?? "").toUpperCase();
    const failure = result?.failure;
    const acquisition =
      code.startsWith("GIT.") ||
      code === "TIMEOUT:ACQUIRE" ||
      failure?.operation === "clone" ||
      failure?.operation === "checkout";
    if (acquisition) {
      return {
        kind: "blocked",
        title: "Repository checkout failed",
        body:
          result?.message && result.message !== "Run did not complete."
            ? result.message
            : "Medha could not check out the repository, so analysis and every later phase did not run.",
        cta: "Inspect failure",
        score: null,
        risk,
      };
    }
    const body =
      result?.message && result.message !== "Run did not complete."
        ? result.message
        : verification?.summary && verification.summary !== "Verification has not started."
          ? verification.summary
          : blockedByVerification
            ? "A blocking check remains unresolved."
            : "This run did not complete.";
    // Blocked-before-execution vs failed-after-execution: execution began
    // when the pipeline left EXECUTE pending or the CEG recorded nodes.
    // A critic score is a code-review assessment, never a deployment score —
    // it stays in the verification panel under its own label, so a failed
    // run never shows "100 / 100" beside its outcome.
    const executeStage = snapshot.pipeline.find((p) => p.id === "EXECUTE")?.status;
    const executed =
      snapshot.graph.nodes.length > 0 ||
      (executeStage != null && executeStage !== "pending" && executeStage !== "skipped");
    return {
      kind: "blocked",
      title: executed ? "Deployment failed" : "Deployment blocked",
      body,
      cta: executed ? "Inspect failure" : "Inspect evidence",
      score: null,
      risk,
    };
  }

  if (runStatus === "awaiting_approval") {
    return {
      kind: "awaiting",
      title: "Waiting for approval",
      body:
        result?.message && result.message !== "Run completed."
          ? result.message
          : "The verified plan is ready. Review the evidence, then approve or reject it.",
      cta: "Review proposal",
      score,
      risk,
    };
  }

  if (runStatus === "succeeded") {
    const conflictNote =
      snapshot.negotiation?.status === "resolved" &&
      snapshot.negotiation.conflictSummary &&
      !snapshot.negotiation.conflictSummary.toLowerCase().includes("no conflict")
        ? "The detected conflict was resolved before execution."
        : "All required verification checks passed.";
    return {
      kind: "approved",
      title: "Deployment approved",
      body: result?.message && result.message !== "Run completed." ? result.message : conflictNote,
      cta: "View evidence",
      score,
      risk,
    };
  }

  return {
    kind: "unknown",
    title: "Not evaluated yet",
    body: "This run has not produced a decision yet.",
    cta: "View details",
    score: null,
    risk,
  };
}

export interface JourneyStep {
  label: string;
  done: boolean;
  active: boolean;
}

function stageStatus(snapshot: DeploymentSnapshot, id: string): string | null {
  return snapshot.pipeline.find((p) => p.id === id)?.status ?? null;
}

function isDone(status: string | null): boolean {
  return status === "success" || status === "warning";
}

/** Human-readable verification journey derived from real backend state. */
export function getJourney(snapshot: DeploymentSnapshot): JourneyStep[] {
  const analyzed =
    isDone(stageStatus(snapshot, "ANALYZE")) || snapshot.changeIntel != null;
  const impact =
    snapshot.changeIntel != null || isDone(stageStatus(snapshot, "PLAN"));
  const negotiation = snapshot.negotiation;
  const conflictResolved =
    negotiation?.status === "resolved" ||
    isDone(stageStatus(snapshot, "NEGOTIATE")) ||
    isDone(stageStatus(snapshot, "VERIFY"));
  const noConflict =
    negotiation == null && snapshot.constraints.length === 0 && conflictResolved;
  void noConflict;
  const verified =
    snapshot.verification?.passed === true || isDone(stageStatus(snapshot, "VERIFY"));
  const executed =
    snapshot.graph.nodes.length > 0 || isDone(stageStatus(snapshot, "EXECUTE"));
  const confirmed =
    snapshot.runStatus === "succeeded" ||
    snapshot.runStatus === "failed" ||
    snapshot.runStatus === "awaiting_approval" ||
    snapshot.runStatus === "partial_recovery";

  const steps: JourneyStep[] = [
    { label: "Change analyzed", done: analyzed, active: false },
    { label: "Impact identified", done: impact, active: false },
    { label: "Conflict resolved", done: conflictResolved, active: false },
    { label: "Safety verified", done: verified, active: false },
    { label: "Deployment executed", done: executed, active: false },
    { label: "Result confirmed", done: confirmed, active: false },
  ];
  if (snapshot.runStatus === "running") {
    const firstPending = steps.findIndex((s) => !s.done);
    if (firstPending >= 0) steps[firstPending].active = true;
  }
  return steps;
}

export function conflictCount(snapshot: DeploymentSnapshot): number {
  return snapshot.constraints.filter(
    (c) => c.status === "conflict" || c.status === "superseded" || c.status === "rejected",
  ).length;
}

export function checksSummary(snapshot: DeploymentSnapshot): {
  passed: number;
  total: number;
} | null {
  const checks = snapshot.verification?.checks;
  if (!checks || checks.length === 0) return null;
  return {
    passed: checks.filter((c) => c.status === "pass").length,
    total: checks.length,
  };
}
