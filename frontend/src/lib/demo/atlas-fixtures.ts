/** Atlas Commerce deterministic demo fixtures — three-month-old fictional repository.
 *
 *  All data is coherent across every dashboard panel.  The same commit, run,
 *  CEG nodes, negotiation conflict, verification checks, alerts, and service
 *  states are used by every component so that no panel disagrees with another.
 *
 *  IMPORTANT: These are synthetic demonstration data.  They do not reflect real
 *  production telemetry and are only active when no real project is selected.
 */

import type {
  CegNode,
  CegEdge,
  ConstraintView,
  NegotiationView,
  VerificationCheck,
  VerificationView,
} from "@/lib/demo/types";

// — Contributors —
export const ATLAS_CONTRIBUTORS = [
  { initials: "PS", name: "Priya S.", role: "API", commits: 12 },
  { initials: "RK", name: "Rahul K.", role: "Infrastructure", commits: 9 },
  { initials: "MT", name: "Maya T.", role: "Frontend", commits: 8 },
  { initials: "DL", name: "Diego L.", role: "DevOps", commits: 7 },
  { initials: "ER", name: "Elena R.", role: "QA", commits: 5 },
  { initials: "SY", name: "Sam Y.", role: "Documentation", commits: 4 },
];

// — Latest push (canonical fixture) —
export const ATLAS_LATEST_PUSH = {
  commitHash: "a82f31c",
  shortHash: "a82f31c",
  author: "Priya S.",
  authorInitials: "PS",
  title: "Optimize checkout queries",
  summary: "Adds query batching and an index for order lookups.",
  changedFiles: 3,
  additions: 124,
  deletions: 38,
  commitTimestamp: "2026-10-10T14:32:00Z",
  relativeTimestamp: "18 min ago",
  checks: { passed: 2, pending: 1, total: 3 },
  relatedServices: ["backend", "database"],
};

// — Deployment history (3 months, Sept 12 – Oct 12, 2026) —
// Every panel agrees about the same project, commit, run, alert, and service states.
export const ATLAS_DEPLOYMENTS = [
  {
    deploymentId: "dep_atlas_001",
    scenario: "SUCCESSFUL_DEPLOYMENT",
    status: "completed",
    mode: "demo",
    started: "2026-09-13T09:15:00Z",
    completed: "2026-09-13T09:32:00Z",
    duration: "~17s",
    title: "Initial successful deployment",
    verificationScore: 94,
    constraintsResolved: 0,
    resultKind: "success",
    cegNodes: 5,
    cegEdges: 4,
    summary: "All services healthy. No conflicts.",
  },
  {
    deploymentId: "dep_atlas_002",
    scenario: "PORT_CONFLICT",
    status: "completed",
    mode: "demo",
    started: "2026-09-20T14:30:00Z",
    completed: "2026-09-20T14:55:00Z",
    duration: "~25s",
    title: "Port conflict: Docker and Nginx claimed port 8080",
    verificationScore: 91,
    constraintsResolved: 1,
    resultKind: "success",
    cegNodes: 5,
    cegEdges: 4,
    summary: "Nginx remapped to 8081. Conflict resolved via alternative.",
  },
  {
    deploymentId: "dep_atlas_003",
    scenario: "SECURITY_CONFLICT",
    status: "completed",
    mode: "demo",
    started: "2026-09-27T16:00:00Z",
    completed: "2026-09-27T16:30:00Z",
    duration: "~30s",
    title: "Security policy enforced over preference",
    verificationScore: 96,
    constraintsResolved: 1,
    resultKind: "success",
    cegNodes: 5,
    cegEdges: 4,
    summary: "Security constraint won; unsafe preference rejected.",
  },
  {
    deploymentId: "dep_atlas_004",
    scenario: "VERIFICATION_FAILURE",
    status: "partial_recovery",
    mode: "demo",
    started: "2026-10-04T10:00:00Z",
    completed: "2026-10-04T10:22:00Z",
    duration: "~22s",
    title: "Verification failure — missing env var, bounded replan",
    verificationScore: 90,
    constraintsResolved: 0,
    resultKind: "partial_recovery",
    cegNodes: 5,
    cegEdges: 4,
    summary: "DATABASE_URL missing; replanned within retry limit. Backend failed; frontend rolled back; analytics preserved.",
  },
  {
    deploymentId: "dep_atlas_005",
    scenario: "PARTIAL_FAILURE",
    status: "partial_recovery",
    mode: "demo",
    started: "2026-10-10T11:00:00Z",
    completed: "2026-10-10T11:18:00Z",
    duration: "~18s",
    title: "Latest run — degraded worker, scoped rollback",
    verificationScore: 87,
    constraintsResolved: 1,
    resultKind: "partial_recovery",
    cegNodes: 5,
    cegEdges: 6,
    summary: "Background worker degraded. Scoped rollback rolled back frontend only. Network, database, analytics preserved.",
  },
];

// — CEG nodes (deterministic positions, shared across deployments) —
export const ATLAS_CEG_NODES: CegNode[] = [
  {
    id: "n_network",
    node_id: "n_network",
    service: "NETWORK",
    action: "create_network",
    status: "preserved",
    timestamp: "11:00:00",
    dependencies: [],
    parent_nodes: [],
    position: { x: 280, y: 0 },
    is_demo: true,
    reason: "Independent infrastructure — not affected by any failure",
    dependents: ["n_backend"],
    preserved: true,
    rollbackRequired: false,
  },
  {
    id: "n_database",
    node_id: "n_database",
    service: "DATABASE",
    action: "start_container",
    status: "preserved",
    timestamp: "11:02:00",
    dependencies: ["n_network"],
    parent_nodes: ["n_network"],
    position: { x: 80, y: 120 },
    is_demo: true,
    reason: "Upstream success retained through rollback",
    dependents: ["n_backend"],
    preserved: true,
    rollbackRequired: false,
  },
  {
    id: "n_backend",
    node_id: "n_backend",
    service: "BACKEND",
    action: "start_container",
    status: "failed",
    timestamp: "11:05:00",
    dependencies: ["n_database"],
    parent_nodes: ["n_database"],
    position: { x: 80, y: 250 },
    is_demo: true,
    reason: "Health check failed after start; elevated retry rates",
    dependents: ["n_frontend"],
    rollbackRequired: true,
    preserved: false,
  },
  {
    id: "n_frontend",
    node_id: "n_frontend",
    service: "FRONTEND",
    action: "start_container",
    status: "rolled_back",
    timestamp: "11:08:00",
    dependencies: ["n_backend"],
    parent_nodes: ["n_backend"],
    position: { x: 80, y: 380 },
    is_demo: true,
    reason: "Dependent on failed backend; reversed during rollback",
    dependents: [],
    rollbackRequired: true,
    preserved: false,
  },
  {
    id: "n_analytics",
    node_id: "n_analytics",
    service: "ANALYTICS",
    action: "start_container",
    status: "preserved",
    timestamp: "11:01:00",
    dependencies: ["n_network"],
    parent_nodes: ["n_network"],
    position: { x: 480, y: 120 },
    is_demo: true,
    reason: "Causally independent branch kept running",
    dependents: [],
    preserved: true,
    rollbackRequired: false,
  },
];

export const ATLAS_CEG_EDGES: CegEdge[] = [
  { id: "e1", source: "n_network", target: "n_database", relation: "depends_on" },
  { id: "e2", source: "n_network", target: "n_analytics", relation: "depends_on" },
  { id: "e3", source: "n_database", target: "n_backend", relation: "depends_on" },
  { id: "e4", source: "n_backend", target: "n_frontend", relation: "depends_on" },
  { id: "e5", source: "n_backend", target: "n_frontend", relation: "depends_on" },
  { id: "e6", source: "n_network", target: "n_analytics", relation: "depends_on" },
];

// — Constraint negotiation fixture for Atlas Commerce —
// The port conflict between Docker (backend) and Nginx is the active conflict.
// It was resolved in deployment dep_atlas_002 (port 8080→8081) and is reflected
// in the latest run (dep_atlas_005) as a contributing factor to the worker degradation.
export const ATLAS_NEGOTIATION: NegotiationView = {
  title: "CONSTRAINT NEGOTIATION",
  conflictSummary: "Docker and Nginx claimed host port 8080",
  round: 1,
  maxRounds: 3,
  status: "resolved",
  resolution: "8081 selected for Nginx",
method: "ALTERNATIVE",
  involvedConstraintIds: ["c_port_docker", "c_port_nginx"],
  simpleExplanation: "Two deployment components requested the same port. MEDHA detected the conflict before execution and selected an available alternative.",
  technicalNotes: [
    "conflict_id=cf_port_8080",
    "type=PORT_CLAIM",
    "key=host:8080",
    "priority=RESOURCE vs RESOURCE",
    "old_value=8080",
    "new_value=8081",
    "winner=c_port_docker",
    "loser=c_port_nginx",
    "rounds_used=1",
  ],
};

// — Verification checks for the latest (partial recovery) run —
// Two checks passed, one pending (DATABASE_URL connected to degraded worker).
export const ATLAS_VERIFICATION_CHECKS: VerificationCheck[] = [
  {
    id: "check_schema",
    name: "Schema",
    status: "pass",
    message: "Configs match schema",
    category: "configuration",
    rule: "schema_compliance",
  },
  {
    id: "check_yaml",
    name: "YAML",
    status: "pass",
    message: "YAML parses cleanly",
    category: "configuration",
    rule: "yaml_parse",
  },
  {
    id: "check_compose",
    name: "Compose",
    status: "pass",
    message: "Compose graph valid",
    category: "configuration",
    rule: "compose_valid",
  },
  {
    id: "check_security",
    name: "Security",
    status: "pass",
    message: "Security floor intact",
    category: "security",
    rule: "security_floor",
  },
  {
    id: "check_constraints",
    name: "Constraints",
    status: "pass",
    message: "Agreed set consistent",
    category: "constraints",
    rule: "constraint_consistency",
  },
  {
    id: "check_env",
    name: "Environment",
    status: "pending",
    message: "DATABASE_URL present for worker config",
    category: "configuration",
    rule: "required_env_var",
  },
];

// — Active alerts for the latest run —
// Three coherent alerts connecting to the fixture data.
export const ATLAS_ALERTS = [
  {
    id: "alert_redis",
    severity: "high",
    title: "Redis connection failures",
    description: "Elevated retry rates detected on the background worker; 47 failed connection attempts in the last minute. May be related to the degraded worker state.",
    affectedService: "background worker",
    timestamp: "2026-10-10T11:14:00Z",
    relatedRun: "dep_atlas_005",
    investigationPath: "Check Redis connectivity, review connection pool settings, verify worker heartbeat",
    severityColor: "red",
  },
  {
    id: "alert_vulnerability",
    severity: "medium",
    title: "Dependency vulnerability requiring review",
    description: "PostgreSQL driver version 2.3.5 has a known CVE. Schedule update in the next release cycle.",
    affectedService: "API service",
    timestamp: "2026-10-08T09:30:00Z",
    relatedRun: "dep_atlas_003",
    investigationPath: "Run dependency audit, update postgres driver, verify compatibility",
    severityColor: "amber",
  },
  {
    id: "alert_drift",
    severity: "medium",
    title: "Deployment configuration drift",
    description: "Nginx configuration has drifted from the canonical spec; port 8080 reference persists despite port-conflict resolution. Update config to reference 8081.",
    affectedService: "nginx",
    timestamp: "2026-10-09T15:20:00Z",
    relatedRun: "dep_atlas_002",
    investigationPath: "Apply configuration drift remediation, redeploy nginx",
    severityColor: "amber",
  },
];

// — Service health states —
// Five services with statuses connecting to the fixture. The degraded background
// worker connects logically to the Redis alert above.
export const ATLAS_SERVICE_HEALTH = [
  { service: "web frontend", status: "healthy", endpoint: "http://localhost:3000", latencyMs: 42 },
  { service: "API service", status: "healthy", endpoint: "http://localhost:8080", latencyMs: 28 },
  { service: "background worker", status: "degraded", endpoint: "http://localhost:8081/worker/health", latencyMs: 310, connectsToAlert: "alert_redis" },
  { service: "PostgreSQL", status: "healthy", endpoint: "postgresql://localhost:5432/atlas_commerce", latencyMs: 15 },
  { service: "Redis", status: "elevated_retries", endpoint: "redis://localhost:6379", latencyMs: 85, connectsToAlert: "alert_redis" },
];

// — 30-day deployment success rate data (Sept 12 – Oct 12, 2026) —
// One data point per day. Every point comes from the fixture deployment history.
export const ATLAS_DEPLOYMENT_TREND = [
  { date: "2026-09-12", success: true },
  { date: "2026-09-13", success: true },
  { date: "2026-09-14", success: false },
  { date: "2026-09-15", success: true },
  { date: "2026-09-16", success: true },
  { date: "2026-09-17", success: true },
  { date: "2026-09-18", success: true },
  { date: "2026-09-19", success: true },
  { date: "2026-09-20", success: true },
  { date: "2026-09-21", success: true },
  { date: "2026-09-22", success: true },
  { date: "2026-09-23", success: true },
  { date: "2026-09-24", success: true },
  { date: "2026-09-25", success: true },
  { date: "2026-09-26", success: true },
  { date: "2026-09-27", success: true },
  { date: "2026-09-28", success: true },
  { date: "2026-09-29", success: true },
  { date: "2026-09-30", success: true },
  { date: "2026-10-01", success: true },
  { date: "2026-10-02", success: true },
  { date: "2026-10-03", success: true },
  { date: "2026-10-04", success: false },
  { date: "2026-10-05", success: true },
  { date: "2026-10-06", success: true },
  { date: "2026-10-07", success: true },
  { date: "2026-10-08", success: true },
  { date: "2026-10-09", success: true },
  { date: "2026-10-10", success: false },
  { date: "2026-10-11", success: true },
  { date: "2026-10-12", success: true },
];

// — Bounded replanning attempt for verification failure —
export const ATLAS_REPLAN_ATTEMPT = {
  attempt: 1,
  maxReplan: 1,
  fix: "inject_DATABASE_URL",
  description: "MEDHA found a configuration problem and is replanning within the allowed retry limit.",
  originalPlan: "deploy atlantis services",
  revisedPlan: "deploy with DATABASE_URL injected into worker config",
};

// — Recent activity entries (compact) —
export const ATLAS_RECENT_ACTIVITY = [
  {
    timestamp: "2026-10-10T11:00:00Z",
    title: "Deployment dep_atlas_005 completed",
    description: "Partial recovery: background worker degraded, frontend rolled back, analytics preserved.",
    type: "deployment",
  },
  {
    timestamp: "2026-10-10T10:55:00Z",
    title: "Constraint conflict resolved",
    description: "Nginx remapped from port 8080 to 8081. ALTERNATIVE method. Round 1 of 3.",
    type: "negotiation",
  },
  {
    timestamp: "2026-10-10T10:45:00Z",
    title: "Verification started",
    description: "6 checks — 4 passed, 1 pending (DATABASE_URL), 1 failed gate.",
    type: "verification",
  },
  {
    timestamp: "2026-10-10T10:30:00Z",
    title: "CEG updated — 5 nodes, 6 edges",
    description: "Execution graph reflects partial failure with scoped rollback.",
    type: "graph",
  },
  {
    timestamp: "2026-10-10T10:15:00Z",
    title: "Latest push a82f31c — Optimize checkout queries",
    description: "Priya S. added query batching and index for order lookups. +124/-38, 3 files.",
    type: "push",
  },
];