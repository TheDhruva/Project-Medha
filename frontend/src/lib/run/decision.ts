import type { DeploymentSnapshot } from "@/lib/demo/types";

export type DecisionKind = "approved" | "blocked" | "recovered" | "running" | "unknown";

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
    const blockedByCritic =
      critic?.recommendation === "BLOCK" || critic?.recommendation === "WARN";
    void blockedByCritic;
    const body =
      result?.message && result.message !== "Run did not complete."
        ? result.message
        : verification?.summary && verification.summary !== "Verification has not started."
          ? verification.summary
          : blockedByVerification
            ? "A blocking check remains unresolved."
            : "This run did not complete.";
    return {
      kind: "blocked",
      title: "Deployment blocked",
      body,
      cta: "Inspect evidence",
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
