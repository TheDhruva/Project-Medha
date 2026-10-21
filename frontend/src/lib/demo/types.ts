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
  /** Absent on older persisted runs — always guard before reading. */
  involvedConstraintIds?: string[];
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
  /** Structured failure/block code (e.g. MULTIPLE_APPS_REQUIRE_TARGET); absent on older payloads. */
  code?: string | null;
  /** Target-selection detail for target-related blocks; absent otherwise. */
  target_selection?: TargetSelectionView | null;
  /** Analysis outcome, distinct from the (possibly blocked) deployment. */
  analysis_status?: string | null;
  deployment_status?: string | null;
  /** Comprehensive repository inventory; present whenever analysis ran. */
  repository_analysis?: RepositoryAnalysisView | null;
  /** Structured build-stage diagnostics; present only when a build failed. */
  build?: BuildDiagnosticsView | null;
}

export interface BuildDiagnosticsView {
  stage?: string;
  profile?: string | null;
  app_root?: string | null;
  package_manager?: string | null;
  command?: string | null;
  exit_code?: number | null;
  error_code?: string | null;
  log?: string | null;
  log_truncated?: boolean;
}

export interface RepositoryAnalysisView {
  schema?: string;
  analysis_status?: string;
  commit_sha?: string | null;
  applications?: { path: string; technologies?: string[] }[];
  languages?: { language: string }[];
  finding_count?: number;
  coverage?: { gaps?: string[] };
  tasks?: { task: string; status: string }[];
  revision?: {
    sha?: string | null;
    available?: boolean;
    reason?: string | null;
  } | null;
}

export interface TargetCandidateView {
  path: string;
  technologies: string[];
  evidence: string[];
}

export interface TargetSelectionView {
  candidates: TargetCandidateView[];
  relationship?: string | null;
  reason?: string | null;
  next_actions?: string[];
  supported_targets?: string[];
  selected_target?: string | null;
  project_id?: string | null;
}

export interface TraceEvent {
  id: string;
  time: string;
  tone: "success" | "warning" | "error" | "info" | "neutral";
  message: string;
  technical?: string;
}

/** How the run actually executed — from GET /logs `execution_mode`, never guessed. */
export type ExecutionMode =
  | "demo"
  | "simulator"
  | "controlled_test"
  | "real"
  | "unconfigured";

/** Real container stdout/stderr from GET /logs `runtime_logs` (null = none). */
export interface RuntimeLogsView {
  available: boolean;
  container?: string | null;
  code?: string | null;
  stdout?: string;
  stderr?: string;
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
  executionMode: ExecutionMode | null;
  runtimeLogs: RuntimeLogsView | null;
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
  /** Measured wall-clock seconds (result timings, else created/updated diff); null when unknown. */
  durationSeconds: number | null;
}

export interface DeployFormState {
  repositoryUrl: string;
  targetHost: string;
  targetPort: string;
  intent: string;
  scenario: null;
  mode: "real";
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
