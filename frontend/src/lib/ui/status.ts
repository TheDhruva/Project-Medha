import type {
  AgentStatus,
  CheckStatus,
  ConstraintStatus,
  NodeStatus,
  StageStatus,
} from "@/lib/demo/types";

export function stageTone(status: StageStatus): string {
  switch (status) {
    case "running":
      return "border-medha-accent bg-medha-accent-soft text-medha-accent-ink";
    case "success":
      return "border-medha-success/30 bg-medha-success-soft text-medha-success";
    case "warning":
      return "border-medha-warning/30 bg-medha-warning-soft text-medha-warning";
    case "failed":
      return "border-medha-danger/30 bg-medha-danger-soft text-medha-danger";
    case "skipped":
      return "border-medha-border bg-medha-muted text-medha-tertiary";
    default:
      return "border-medha-border bg-white text-medha-secondary";
  }
}

export function statusGlyph(
  status: StageStatus | AgentStatus | CheckStatus | NodeStatus | ConstraintStatus,
): string {
  switch (status) {
    case "success":
    case "complete":
    case "pass":
    case "accepted":
    case "preserved":
      return "✓";
    case "warning":
    case "conflict":
      return "⚠";
    case "failed":
    case "fail":
    case "rejected":
      return "✕";
    case "running":
      return "●";
    case "rolled_back":
    case "superseded":
      return "↶";
    case "skipped":
      return "–";
    default:
      return "○";
  }
}

export function labelStatus(
  status: StageStatus | AgentStatus | CheckStatus | NodeStatus | ConstraintStatus,
): string {
  return String(status).replace(/_/g, " ").toUpperCase();
}

export type RunSource = "DEMO" | "LIVE";

/** Derive the run source label from actual state (never a hardcoded badge).
 *
 * `selectedMode` is the mode chosen in the deployment form; `activeIsDemo` is
 * the is_demo flag of the running/completed snapshot. Either one being demo
 * makes the UI say DEMO — matching Header's `form.mode === "demo" || snapshot.isDemo`.
 */
export function runSourceLabel(
  selectedMode: "demo" | "real",
  activeIsDemo: boolean,
): RunSource {
  return selectedMode === "demo" || activeIsDemo ? "DEMO" : "LIVE";
}
