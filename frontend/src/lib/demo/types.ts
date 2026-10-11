/** MEDHA shared UI types — used by demo fixtures, API event mapping, and live runs. */

export type ScenarioId =
  | "SUCCESSFUL_DEPLOYMENT"
  | "PORT_CONFLICT"
  | "SECURITY_CONFLICT"
  | "VERIFICATION_FAILURE"
  | "PARTIAL_FAILURE";

export type ViewMode = "simple" | "technical";

export type StageId =
  | "PREFLIGHT"
  | "ANALYZE"
  | "PLAN"
  | "AGENTS"
  | "NEGOTIATE"
  | "VERIFY"
  | "EXECUTE"
  | "RECOVER"
  | "COMPLETE";

export type StageStatus =
  | "pending"
  | "running"
  | "success"
  | "warning"
  | "failed"
  | "skipped";

export type AgentId =
  | "preflight"
  | "analyzer"
  | "docker"
  | "nginx"
  | "security"
  | "mediator"
  | "verifier"
  | "critic"
  | "executor"
  | "rollback";

export type AgentStatus =
  | "idle"
  | "running"
  | "complete"
  | "warning"
  | "failed"
  | "skipped";

export type ConstraintType =
  | "PORT_CLAIM"
  | "ENV_VAR"
  | "VOLUME_MOUNT"
  | "NETWORK_POLICY"
  | "SECURITY_POLICY"
  | "EXEC_ORDER";

export type ConstraintPriority =
  | "SECURITY"
  | "RESOURCE"
  | "DEPENDENCY"
  | "PREFERENCE";

export type ConstraintStatus =
  | "proposed"
  | "accepted"
  | "rejected"
  | "superseded"
  | "conflict";

export type CheckStatus = "pending" | "pass" | "warning" | "fail";

export type NodeStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "rolled_back"
  | "preserved";

export type DeploymentRunStatus =
  | "idle"
  | "running"
  | "awaiting_approval"
  | "succeeded"
  | "failed"
  | "partial_recovery";

export type ResultKind = "success" | "partial_recovery" | "failed" | "plan_awaiting_approval";

export interface ScenarioMeta {
  id: ScenarioId;
  name: string;
  description: string;
  expectedBehavior: string;
}

export interface PipelineStage {
  id: StageId;
  label: string;
  status: StageStatus;
  detail: string;
  durationMs?: number;
}

export interface AgentActivity {
  id: AgentId;
  name: string;
  status: AgentStatus;
  activity: string;
  lastEvent: string;
  durationMs?: number;
}

export interface ConstraintView {
  id: string;
  type: ConstraintType;
  priority: ConstraintPriority;
  sourceAgent: string;
  service?: string;
  summary: string;
  detail: string;
  status: ConstraintStatus;
  technical?: {
    payload: Record<string, string | number | boolean>;
  };
}

export interface NegotiationView {
  title: string;
  conflictSummary: string;
  round: number;
  maxRounds: number;
  resolution?: string;
  method?: string;
  status: "idle" | "detecting" | "resolving" | "resolved" | "failed" | "none";
  involvedConstraintIds: string[];
  simpleExplanation: string;
  technicalNotes?: string[];
}

export interface VerificationCheck {
  id: string;
  name: string;
  status: CheckStatus;
  message: string;
  rule?: string;
  category?: string;
}

export interface VerificationView {
  checks: VerificationCheck[];
  passed: boolean | null;
  summary: string;
}

export interface CriticBreakdown {
  security: number;
  completeness: number;
  constraints: number;
  intentAlignment: number;
}

export interface CriticView {
  score: number;
  breakdown: CriticBreakdown;
  recommendation: "PASS" | "WARN" | "BLOCK";
  findings: string[];
}

export interface CegNode {
  id: string;
  service: string;
  action: string;
  status: NodeStatus;
  timestamp: string;
  dependencies: string[];
  reason?: string;
  dependents?: string[];
  rollbackRequired?: boolean;
  preserved?: boolean;
  position: { x: number; y: number };
  node_id?: string;
  parent_nodes?: string[];
  is_demo?: boolean;
}

export interface CegEdge {
  id: string;
  source: string;
  target: string;
  relation?: string;
}

export interface CegGraph {
  nodes: CegNode[];
  edges: CegEdge[];
}

// --- Change Intelligence (Phase 2) ---
// The Change Impact Graph (CIG) is repository dependency impact between source
// artifacts. It is deliberately distinct from the CEG (runtime execution
// causality between deployed services). Mirror of backend to_ui() payloads.

export type ChangeType = "modified" | "added" | "deleted" | "renamed";

export interface ChangeCounts {
  modified: number;
  added: number;
  deleted: number;
  renamed: number;
}

export interface ChangeIntelFile {
  path: string;
  old_path: string | null;
  change_type: ChangeType;
  added_lines: number;
  deleted_lines: number;
}

export interface ChangeIntelChangeSet {
  base_revision: string;
  target_revision: string;
  base_sha: string;
  target_sha: string;
  source_method: string;
  is_git: boolean;
  counts: ChangeCounts;
  files: ChangeIntelFile[];
  unsupported: string[];
}

export type ChangeIntelNodeType =
  | "changed"
  | "affected"
  | "context"
  | "test"
  | "config";

export type ChangeIntelRelationship =
  | "import"
  | "call"
  | "reference"
  | "extends"
  | "implements"
  | "inherits"
  | "api-consumer"
  | "schema-consumer"
  | "configuration-dependency"
  | "test-covers"
  | "unknown";

export type ChangeIntelConfidence = "high" | "medium" | "heuristic";

export type ChangeIntelRiskLevel = "high" | "medium" | "low" | "none";

export interface ChangeIntelNode {
  id: string;
  path: string;
  node_type: ChangeIntelNodeType;
  change_type: ChangeType | null;
  symbol: string | null;
  symbol_id: string | null;
  kind: string | null;
  language: string;
  direct: boolean;
}

export interface ChangeIntelEdge {
  id: string;
  source: string;
  target: string;
  relationship: ChangeIntelRelationship;
  confidence: ChangeIntelConfidence;
  evidence: string;
  direct: boolean;
  note: string | null;
}

export interface ChangeIntelGraph {
  nodes: ChangeIntelNode[];
  edges: ChangeIntelEdge[];
}

export interface ChangeIntelUnresolved {
  path: string;
  line: number;
  target: string;
  kind: string;
  reason: string;
}

export interface ChangeIntelTraversal {
  max_depth: number;
  depth_used: number;
  direct_targets: string[];
  transitive_targets: string[];
  cycles_detected: string[][];
}

export interface ChangeIntelRiskFactor {
  code: string;
  level: ChangeIntelRiskLevel;
  reason: string;
}

export interface ChangeIntelRisk {
  level: ChangeIntelRiskLevel;
  factors: ChangeIntelRiskFactor[];
}

export interface ChangeIntelRequirement {
  id: string;
  target_path: string;
  target_symbol: string | null;
  requirement: string;
  reason: string;
  check_category: string;
  executable: boolean;
  status: string;
}

export interface ChangeIntelChangedSymbol {
  id: string;
  name: string;
  fqn: string;
  kind: string;
  path: string;
  line: number;
  end_line: number;
  language: string;
  change_type: ChangeType;
  lines_changed: number;
}

export interface ChangeIntelAnalysis {
  deployment_id: string | null;
  repository_url: string;
  is_demo: boolean;
  label: string | null;
  generated_at: string;
  changeset: ChangeIntelChangeSet;
  changed_symbols: ChangeIntelChangedSymbol[];
  graph: ChangeIntelGraph;
  traversal: ChangeIntelTraversal;
  unresolved: ChangeIntelUnresolved[];
  risk: ChangeIntelRisk;
  requirements: ChangeIntelRequirement[];
}

export interface RollbackSummary {
  headline: string;
  preserved: number;
  failed: number;
  rolledBack: number;
  details: { service: string; status: NodeStatus; note: string }[];
  scopeNodeIds: string[];
  simpleExplanation: string;
}

export interface DeploymentResultView {
  kind: ResultKind;
  title: string;
  message: string;
  durationLabel: string;
  servicesLabel: string;
  verificationScore: number | null;
  constraintsResolved: number;
  rollbackScope: string | null;
}

export interface TraceEvent {
  id: string;
  time: string;
  tone: "success" | "warning" | "error" | "info" | "neutral";
  message: string;
  technical?: string;
}

export interface ExplainabilityState {
  currentStage: StageId | null;
  round: number | null;
  statusLabel: string;
  simpleText: string;
  technicalText: string;
}

export interface DeploymentSnapshot {
  deploymentId: string | null;
  isDemo: boolean;
  scenario: ScenarioId | null;
  runStatus: DeploymentRunStatus;
  explain: ExplainabilityState;
  pipeline: PipelineStage[];
  agents: AgentActivity[];
  constraints: ConstraintView[];
  negotiation: NegotiationView | null;
  verification: VerificationView | null;
  critic: CriticView | null;
  graph: CegGraph;
  selectedNodeId: string | null;
  rollback: RollbackSummary | null;
  result: DeploymentResultView | null;
  trace: TraceEvent[];
  frameIndex: number;
  totalFrames: number;
  changeIntel: ChangeIntelAnalysis | null;
}

export interface DeployFormState {
  repositoryUrl: string;
  targetHost: string;
  targetPort: string;
  intent: string;
  scenario: ScenarioId;
  mode: "demo" | "real";
  baseRevision: string;
  targetRevision: string;
}

export interface DemoFrame {
  /** Partial snapshot updates applied when this frame becomes active */
  patch: Partial<
    Omit<DeploymentSnapshot, "isDemo" | "frameIndex" | "totalFrames">
  >;
  delayMs: number;
}
