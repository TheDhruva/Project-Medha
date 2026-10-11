/** Central typed workspace model for the MEDHA frontend demo layer.
 *  Pages consume this through the store — never by importing fixtures directly.
 *  Names follow DATA_MODEL / API_CONTRACT / CNP / CEG / CIG specs where relevant.
 */

export type ProjectStatus = "never_run" | "ready" | "running" | "failed" | "succeeded" | "recovered";

export interface RepoContext {
  url: string;
  branch: string;
  detectedStack?: string;
  autoDetected: boolean;
}

export interface Project {
  id: string;
  name: string;
  objective: string;
  repo: RepoContext | null;
  scenarioKey: DemoScenarioKey;
  status: ProjectStatus;
  lastActivity: string;
  latestRunId: string | null;
  executionMode: "simulator" | "controlled-local";
  createdAt: string;
}

export type DemoScenarioKey =
  | "empty-workspace"
  | "proposal-ready"
  | "proposal-blocked"
  | "verification-failure"
  | "simulated-success"
  | "failed-scoped-recovery"
  | "superseded-proposal"
  | "interrupted-run"
  | "empty-evaluations"
  | "populated-multi-run";

export type ProposalState = "ready" | "blocked" | "rejected" | "outdated" | "approved" | "changes_requested" | "needs_analysis";

export interface ChangedFile {
  path: string;
  change: "modified" | "added" | "deleted" | "renamed";
  added: number;
  deleted: number;
  diffPreview: string;
}

export interface AffectedComponent {
  id: string;
  name: string;
  kind: string;
  impactPath: string[];
  evidence: string;
  risk: "high" | "medium" | "low";
}

export interface ConstraintSummary {
  id: string;
  type: string;
  priority: "SECURITY" | "RESOURCE" | "DEPENDENCY" | "PREFERENCE";
  summary: string;
  status: "proposed" | "accepted" | "conflict" | "resolved" | "rejected";
  resolution?: string | null;
  rationale?: string;
}

export interface VerificationSummary {
  state: "pass" | "fail" | "warn" | "not_run" | "running";
  passed: number;
  failed: number;
  warnings: number;
  skipped: number;
  notRun: number;
  findings: { severity: "error" | "warning" | "info"; check: string; evidence: string }[];
}

export interface ChangeProposal {
  id: string;
  projectId: string;
  title: string;
  sourceRevision: string;
  previousRevision: string | null;
  state: ProposalState;
  stale: boolean;
  supersededBy: string | null;
  summary: string;
  files: ChangedFile[];
  affected: AffectedComponent[];
  constraints: ConstraintSummary[];
  plan: { step: string; detail: string; reversible: boolean }[];
  verification: VerificationSummary;
  risks: string[];
  assumptions: string[];
  openQuestions: string[];
  target: string;
  mode: "simulator" | "controlled-local";
  history: { at: string; actor: string; action: string }[];
}

export type AgentState = "idle" | "active" | "done" | "blocked" | "failed";

export interface AgentRecord {
  id: string;
  name: string;
  responsibility: string;
  state: AgentState;
  stage: string;
  decisions: string[];
  blockers: string[];
  inputs: string[];
  outputs: string[];
}

export interface CnpConflict {
  id: string;
  title: string;
  priorities: string;
  alternatives: { label: string; outcome: string; selected: boolean }[];
  resolution: string | null;
  rationale: string;
  round: number;
  maxRounds: number;
  status: "active" | "resolved" | "unresolved";
}

export interface RunRecord {
  id: string;
  projectId: string;
  proposalId: string | null;
  scenarioKey: DemoScenarioKey;
  status: "succeeded" | "failed" | "recovered" | "running" | "interrupted" | "blocked";
  startedAt: string;
  duration: string;
  verification: "pass" | "fail" | "warn" | "not_run";
  simulator: boolean;
  summary: string;
  stages: { name: string; state: "done" | "active" | "todo" | "failed" | "skipped" }[];
  events: { at: string; severity: "info" | "warning" | "error" | "success"; message: string; ref?: string }[];
  logs: string[];
  ceg: { nodes: { id: string; label: string; state: string; detail: string }[]; edges: { from: string; to: string; label: string }[] };
  cig: { changed: string[]; affected: string[]; paths: { from: string; to: string; via: string }[] };
  recovery: {
    origin: string;
    affected: string[];
    rollbackScope: string[];
    preserved: string[];
    steps: { label: string; state: "done" | "pending" | "failed" }[];
  } | null;
}

export interface EvalSuite {
  id: string;
  name: string;
  scenarios: number;
  status: "empty" | "complete" | "running";
  results: { scenario: string; outcome: string; verification: string; recovery: string }[];
  failurePatterns: { category: string; count: number }[];
  note: string;
}

export type BoardPanelId =
  | "agents" | "constraints" | "verification" | "causal" | "impact" | "events" | "evaluation";

export interface BoardLayout {
  visible: Record<BoardPanelId, boolean>;
  order: BoardPanelId[];
}

export const DEFAULT_BOARD_LAYOUT: BoardLayout = {
  visible: { agents: true, constraints: true, verification: true, causal: true, impact: true, events: true, evaluation: true },
  order: ["agents", "constraints", "verification", "causal", "impact", "events", "evaluation"],
};

export const BOARD_PANELS: { id: BoardPanelId; title: string }[] = [
  { id: "agents", title: "Agent coordination" },
  { id: "constraints", title: "Constraint negotiation" },
  { id: "verification", title: "Verification & critic" },
  { id: "causal", title: "Causal execution" },
  { id: "impact", title: "Change impact" },
  { id: "events", title: "Recent execution events" },
  { id: "evaluation", title: "Evaluation snapshot" },
];
