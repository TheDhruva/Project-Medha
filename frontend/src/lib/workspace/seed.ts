import type {
  AffectedComponent, AgentRecord, ChangedFile, ChangeProposal, CnpConflict,
  ConstraintSummary, EvalSuite, Project, RunRecord, VerificationSummary,
} from "./types";

const AT = (s: string) => `2026-10-${s}`;

function filesFor(kind: string): ChangedFile[] {
  if (kind === "compose") {
    return [
      { path: "compose.yaml", change: "modified", added: 14, deleted: 6, diffPreview: "@@ services.backend.ports: - \"8080:8080\" → - \"8081:8080\"\n@@ services.backend.environment += DATABASE_URL=${DATABASE_URL}" },
      { path: "nginx/nginx.conf", change: "modified", added: 9, deleted: 4, diffPreview: "@@ upstream backend { server backend:8080; }\n+ listen 8081;  # CNP alternative N-2" },
      { path: "backend/app/config.py", change: "modified", added: 22, deleted: 3, diffPreview: "+ DATABASE_URL = env.required(\"DATABASE_URL\")  # fail-closed" },
    ];
  }
  if (kind === "deps") {
    return [
      { path: "backend/requirements.txt", change: "modified", added: 2, deleted: 1, diffPreview: "+ psycopg[binary]==3.1.19\n- psycopg2==2.9.9" },
      { path: "backend/app/db.py", change: "modified", added: 31, deleted: 8, diffPreview: "+ def get_pool(): ...  # pooled sessions" },
      { path: "backend/tests/test_db_pool.py", change: "added", added: 64, deleted: 0, diffPreview: "+ def test_pool_recycles_stale_connections(): ..." },
    ];
  }
  return [
    { path: "README.md", change: "modified", added: 3, deleted: 1, diffPreview: "+ ## Local demo notes" },
  ];
}

function affectedFor(kind: string): AffectedComponent[] {
  if (kind === "compose") {
    return [
      { id: "backend", name: "backend", kind: "service", impactPath: ["compose.yaml", "backend", "database"], evidence: "compose service dependency + DATABASE_URL reference", risk: "high" },
      { id: "nginx", name: "nginx", kind: "edge-proxy", impactPath: ["nginx.conf", "nginx", "backend"], evidence: "upstream block references backend:8080", risk: "medium" },
      { id: "database", name: "database", kind: "stateful", impactPath: ["compose.yaml", "database"], evidence: "volume mount referenced by backend health check", risk: "medium" },
    ];
  }
  return [
    { id: "backend", name: "backend", kind: "service", impactPath: ["backend/app/db.py", "backend"], evidence: "import edge backend.app.db → backend.app.main", risk: "medium" },
    { id: "tests", name: "backend-tests", kind: "test", impactPath: ["backend/tests/test_db_pool.py", "backend"], evidence: "test-covers edge (heuristic)", risk: "low" },
  ];
}

function constraintsFor(kind: "conflict" | "blocked" | "clean" | "security"): ConstraintSummary[] {
  if (kind === "conflict") {
    return [
      { id: "c_port_docker", type: "PORT_CLAIM", priority: "RESOURCE", summary: "Docker: backend publishes host 8080", status: "conflict" },
      { id: "c_port_nginx", type: "PORT_CLAIM", priority: "RESOURCE", summary: "Nginx: edge proxy publishes host 8080", status: "conflict", resolution: "Nginx → 8081 (alternative N-2)", rationale: "Same-priority RESOURCE conflict: deterministic alternative search selected first free port; bounded round 1 of max 3." },
      { id: "c_sec_nonroot", type: "SECURITY_POLICY", priority: "SECURITY", summary: "Security: containers run as non-root", status: "accepted" },
    ];
  }
  if (kind === "blocked") {
    return [
      { id: "c_db_url", type: "ENV_VAR", priority: "DEPENDENCY", summary: "Backend requires DATABASE_URL", status: "conflict", resolution: null, rationale: "No alternative supplies DATABASE_URL; replanning required (round 1 of max 3)." },
      { id: "c_sec_nonroot", type: "SECURITY_POLICY", priority: "SECURITY", summary: "Security: containers run as non-root", status: "accepted" },
    ];
  }
  if (kind === "security") {
    return [
      { id: "c_sec_ingress", type: "SECURITY_POLICY", priority: "SECURITY", summary: "Security: deny unrestricted ingress 0.0.0.0/0", status: "resolved", resolution: "Unsafe request rejected", rationale: "SECURITY outranks PREFERENCE per CNP hierarchy; deterministic priority resolution, round 1 of max 3." },
      { id: "c_pref_open", type: "NETWORK_POLICY", priority: "PREFERENCE", summary: "Preference: open ingress for debugging", status: "rejected" },
    ];
  }
  return [
    { id: "c_port_backend", type: "PORT_CLAIM", priority: "RESOURCE", summary: "Backend claims host 8080", status: "accepted" },
    { id: "c_sec_nonroot", type: "SECURITY_POLICY", priority: "SECURITY", summary: "Security: containers run as non-root", status: "accepted" },
    { id: "c_order", type: "EXEC_ORDER", priority: "DEPENDENCY", summary: "Database starts before backend", status: "accepted" },
  ];
}

function verificationFor(kind: "pass" | "fail" | "warn" | "none"): VerificationSummary {
  if (kind === "pass") {
    return { state: "pass", passed: 6, failed: 0, warnings: 0, skipped: 1, notRun: 0, findings: [{ severity: "info", check: "compose", evidence: "compose.yaml parses; 5 services pinned to busybox:1.36 labels" }] };
  }
  if (kind === "fail") {
    return { state: "fail", passed: 4, failed: 1, warnings: 1, skipped: 0, notRun: 0, findings: [
      { severity: "error", check: "env-required", evidence: "DATABASE_URL referenced by backend/app/config.py but absent from plan environment" },
      { severity: "warning", check: "health-probe", evidence: "readiness probe advisory: simulator service, recorded skipped" },
    ] };
  }
  if (kind === "warn") {
    return { state: "warn", passed: 5, failed: 0, warnings: 1, skipped: 1, notRun: 0, findings: [{ severity: "warning", check: "health-probe", evidence: "http readiness advisory; container-running check used instead" }] };
  }
  return { state: "not_run", passed: 0, failed: 0, warnings: 0, skipped: 0, notRun: 6, findings: [] };
}

function planFor(kind: string) {
  return [
    { step: "Create network medha-demo", detail: "Isolated bridge; labelled MEDHA-owned", reversible: true },
    { step: "Start database", detail: "busybox:1.36 placeholder; health-gated", reversible: true },
    { step: "Start backend", detail: `Dependent on database (${kind}); env-gated`, reversible: true },
    { step: "Start frontend via nginx", detail: "Dependent on backend; edge publish per CNP", reversible: true },
  ];
}

export const SEED_PROJECTS: Project[] = [
  { id: "proj-fresh", name: "Fresh Workspace", objective: "Stage a first constraint-aware deployment.", repo: { url: "https://github.com/example/medha-sample-app", branch: "main", autoDetected: false }, scenarioKey: "empty-workspace", status: "never_run", lastActivity: AT("02 09:12"), latestRunId: null, executionMode: "simulator", createdAt: AT("02 09:00") },
  { id: "proj-atlas", name: "Atlas Checkout", objective: "Deploy the checkout path securely with evidence.", repo: { url: "https://github.com/example/atlas-shop", branch: "release/2.4", detectedStack: "compose · backend + database + nginx", autoDetected: true }, scenarioKey: "proposal-ready", status: "ready", lastActivity: AT("10 18:40"), latestRunId: null, executionMode: "simulator", createdAt: AT("01 10:00") },
  { id: "proj-harbor", name: "Harbor Ports", objective: "Resolve the 8080 edge-port conflict before execution.", repo: { url: "https://github.com/example/harbor-edge", branch: "fix/edge-ports", autoDetected: false }, scenarioKey: "proposal-blocked", status: "ready", lastActivity: AT("09 14:05"), latestRunId: null, executionMode: "simulator", createdAt: AT("01 11:20") },
  { id: "proj-vault", name: "Vault Hardening", objective: "Verify fail-closed config before local execution.", repo: { url: "C:/src/vault-svc", branch: "main", autoDetected: false }, scenarioKey: "verification-failure", status: "failed", lastActivity: AT("10 11:22"), latestRunId: "run-vault-verify-1", executionMode: "simulator", createdAt: AT("03 09:30") },
  { id: "proj-sunny", name: "Sunny Path", objective: "Demonstrate the clean negotiate → verify → execute path.", repo: { url: "https://github.com/example/sunny-svc", branch: "main", autoDetected: false }, scenarioKey: "simulated-success", status: "succeeded", lastActivity: AT("10 08:02"), latestRunId: "run-sunny-1", executionMode: "simulator", createdAt: AT("02 15:00") },
  { id: "proj-partial", name: "Partial Recovery", objective: "Prove scoped rollback preserves independent services.", repo: { url: "https://github.com/example/partial-svc", branch: "main", autoDetected: false }, scenarioKey: "failed-scoped-recovery", status: "recovered", lastActivity: AT("08 22:41"), latestRunId: "run-partial-1", executionMode: "simulator", createdAt: AT("04 13:00") },
  { id: "proj-race", name: "Race Condition Review", objective: "Handle a proposal superseded by a newer commit.", repo: { url: "https://github.com/example/race-svc", branch: "feat/pricing", autoDetected: false }, scenarioKey: "superseded-proposal", status: "ready", lastActivity: AT("10 19:02"), latestRunId: null, executionMode: "simulator", createdAt: AT("05 09:00") },
  { id: "proj-interrupted", name: "Interrupted Stream", objective: "Inspect a disconnected execution honestly.", repo: { url: "C:/src/edge-svc", branch: "main", autoDetected: false }, scenarioKey: "interrupted-run", status: "running", lastActivity: AT("11 07:15"), latestRunId: "run-interrupted-1", executionMode: "controlled-local", createdAt: AT("06 12:00") },
  { id: "proj-evalempty", name: "Eval Greenfield", objective: "Collect first evaluation evidence.", repo: null, scenarioKey: "empty-evaluations", status: "never_run", lastActivity: AT("07 10:00"), latestRunId: null, executionMode: "simulator", createdAt: AT("07 10:00") },
  { id: "proj-metro", name: "Metro Portfolio", objective: "Compare repeated runs and failure patterns.", repo: { url: "https://github.com/example/metro", branch: "main", detectedStack: "compose · 5 services", autoDetected: true }, scenarioKey: "populated-multi-run", status: "succeeded", lastActivity: AT("11 06:58"), latestRunId: "run-metro-3", executionMode: "simulator", createdAt: AT("01 08:00") },
];

export const SEED_PROPOSALS: ChangeProposal[] = [
  {
    id: "prop-atlas-1", projectId: "proj-atlas", title: "Remap edge port + require DATABASE_URL",
    sourceRevision: "a1b2c3d", previousRevision: "9f8e7d6", state: "ready", stale: false, supersededBy: null,
    summary: "Detected change remaps the Nginx edge port and makes DATABASE_URL mandatory. Impact analysis links compose.yaml to backend, nginx, and database with port-claim evidence.",
    files: filesFor("compose"), affected: affectedFor("compose"), constraints: constraintsFor("conflict"),
    plan: planFor("database-healthy"), verification: verificationFor("pass"),
    risks: ["Edge port remap changes operator runbook URLs."], assumptions: ["Host 8081 is free (preflight check)."],
    openQuestions: ["Should analytics keep the shared network?"], target: "localhost:8081 (simulator)", mode: "simulator",
    history: [{ at: AT("10 18:40"), actor: "medha-analyzer", action: "Proposal created from revisions 9f8e7d6 → a1b2c3d" }],
  },
  {
    id: "prop-harbor-1", projectId: "proj-harbor", title: "Edge 8080 claimed by two agents",
    sourceRevision: "h4rb0r1", previousRevision: "h4rb0r0", state: "blocked", stale: false, supersededBy: null,
    summary: "Both Docker and Nginx agents claim host 8080 at equal RESOURCE priority. CNP alternative search is in progress (round 1 of max 3); approval is disabled until resolution.",
    files: filesFor("compose"), affected: affectedFor("compose"), constraints: constraintsFor("conflict"),
    plan: planFor("database-healthy"), verification: verificationFor("none"),
    risks: ["Starting either service first would collide on 8080."], assumptions: [],
    openQuestions: ["Confirm preferred fallback port if 8081 is occupied."],
    target: "localhost:8080 (simulator)", mode: "simulator",
    history: [{ at: AT("09 14:05"), actor: "mediator", action: "Conflict detected: c_port_docker × c_port_nginx" }],
  },
  {
    id: "prop-vault-1", projectId: "proj-vault", title: "Fail-closed config blocked by verification",
    sourceRevision: "vaU1t99", previousRevision: "vaU1t88", state: "blocked", stale: false, supersededBy: null,
    summary: "Verification gate failed: DATABASE_URL is required but missing. One bounded replan (round 1 of max 3) is proposed; execution is blocked until the gate passes.",
    files: filesFor("compose"), affected: affectedFor("compose"), constraints: constraintsFor("blocked"),
    plan: planFor("env-fix"), verification: verificationFor("fail"),
    risks: ["Deploying without DATABASE_URL would crash backend at boot."], assumptions: ["Secret will be supplied via local env, never stored in UI."],
    openQuestions: ["Who provides DATABASE_URL for controlled-local execution?"],
    target: "localhost:8080 (simulator)", mode: "simulator",
    history: [
      { at: AT("10 11:20"), actor: "verifier", action: "Gate FAILED: env-required (DATABASE_URL missing)" },
      { at: AT("10 11:22"), actor: "mediator", action: "Replan round 1 proposed: inject DATABASE_URL from local env" },
    ],
  },
  {
    id: "prop-race-old", projectId: "proj-race", title: "Pricing tweak (superseded)",
    sourceRevision: "r4c3o1d", previousRevision: "r4c3b4s3", state: "outdated", stale: true, supersededBy: "prop-race-new",
    summary: "This proposal targeted r4c3o1d, but a newer commit r4c3n3w arrived before approval. Approval is invalidated; re-analysis of the newer revision is required.",
    files: filesFor("deps"), affected: affectedFor("deps"), constraints: constraintsFor("clean"),
    plan: planFor("db-pool"), verification: verificationFor("none"),
    risks: [], assumptions: [], openQuestions: ["Review the newer revision instead."],
    target: "localhost:8080 (simulator)", mode: "simulator",
    history: [
      { at: AT("10 18:50"), actor: "medha-analyzer", action: "Proposal created for r4c3o1d" },
      { at: AT("10 19:02"), actor: "medha-analyzer", action: "Superseded by r4c3n3w — approval invalidated" },
    ],
  },
  {
    id: "prop-race-new", projectId: "proj-race", title: "Pricing + pool sizing (current)",
    sourceRevision: "r4c3n3w", previousRevision: "r4c3o1d", state: "ready", stale: false, supersededBy: null,
    summary: "Current proposal for the newest commit. Connection pooling change with test coverage; no conflicts; verification requirements attached.",
    files: filesFor("deps"), affected: affectedFor("deps"), constraints: constraintsFor("clean"),
    plan: planFor("db-pool"), verification: verificationFor("pass"),
    risks: ["Pool sizing changes DB connection count."], assumptions: ["Target DB accepts 20 pooled connections."],
    openQuestions: [],
    target: "localhost:8080 (simulator)", mode: "simulator",
    history: [{ at: AT("10 19:02"), actor: "medha-analyzer", action: "Proposal created from revisions r4c3o1d → r4c3n3w" }],
  },
];

export const SEED_AGENTS: Record<string, AgentRecord[]> = {
  "proj-atlas": [
    { id: "analyzer", name: "Code Analyzer", responsibility: "Infer stack + changed artifacts from revisions.", state: "done", stage: "ANALYZE", decisions: ["Stack: compose · backend+db+nginx"], blockers: [], inputs: ["revisions 9f8e7d6→a1b2c3d"], outputs: ["ApplicationProfile"] },
    { id: "docker", name: "Docker", responsibility: "Publish port/volume constraints.", state: "done", stage: "AGENTS", decisions: ["c_port_docker: host 8080"], blockers: [], inputs: ["compose.yaml"], outputs: ["PORT_CLAIM"] },
    { id: "nginx", name: "Nginx", responsibility: "Publish edge-proxy constraints.", state: "done", stage: "AGENTS", decisions: ["c_port_nginx: host 8080"], blockers: ["conflict on 8080"], inputs: ["nginx.conf"], outputs: ["PORT_CLAIM"] },
    { id: "security", name: "Security", responsibility: "Enforce non-root + ingress policy.", state: "done", stage: "AGENTS", decisions: ["c_sec_nonroot accepted"], blockers: [], inputs: ["plan"], outputs: ["SECURITY_POLICY"] },
    { id: "mediator", name: "Mediator (CNP)", responsibility: "Resolve conflicts within max 3 rounds.", state: "done", stage: "NEGOTIATE", decisions: ["Nginx → 8081 (round 1)"], blockers: [], inputs: ["2 PORT_CLAIM"], outputs: ["NegotiationResult"] },
    { id: "verifier", name: "Verifier", responsibility: "Hard gate before execution.", state: "active", stage: "VERIFY", decisions: [], blockers: [], inputs: ["agreed plan"], outputs: [] },
    { id: "critic", name: "Critic", responsibility: "Structured score + findings.", state: "idle", stage: "VERIFY", decisions: [], blockers: [], inputs: [], outputs: [] },
    { id: "executor", name: "Executor", responsibility: "Simulator execution; CEG nodes.", state: "idle", stage: "EXECUTE", decisions: [], blockers: ["awaiting gate"], inputs: [], outputs: [] },
    { id: "rollback", name: "Rollback", responsibility: "Scoped undo on failure.", state: "idle", stage: "RECOVER", decisions: [], blockers: [], inputs: [], outputs: [] },
    { id: "preflight", name: "Preflight", responsibility: "Host/port/workspace checks.", state: "done", stage: "PREFLIGHT", decisions: ["localhost OK; 8081 free"], blockers: [], inputs: ["target"], outputs: [] },
  ],
};

export function agentsFor(projectId: string): AgentRecord[] {
  if (SEED_AGENTS[projectId]) return SEED_AGENTS[projectId];
  const base = SEED_AGENTS["proj-atlas"];
  return base.map((a) => ({ ...a, decisions: [...a.decisions], blockers: [...a.blockers], inputs: [...a.inputs], outputs: [...a.outputs] }));
}

export const SEED_CONFLICTS: Record<string, CnpConflict[]> = {
  "proj-atlas": [
    { id: "conf-port", title: "Host 8080 claimed twice", priorities: "RESOURCE × RESOURCE (equal — alternative search)", status: "resolved",
      alternatives: [
        { label: "N-1: backend moves to 8081", outcome: "Rejected — backend health checks assume 8080", selected: false },
        { label: "N-2: nginx moves to 8081", outcome: "Selected — edge remap is reversible", selected: true },
      ],
      resolution: "Nginx publishes 8081; backend keeps 8080", rationale: "Equal-priority conflict resolved by deterministic alternative search in round 1 of max 3. No LLM call; recorded inputs and outcome only.", round: 1, maxRounds: 3 },
  ],
  "proj-harbor": [
    { id: "conf-port", title: "Host 8080 claimed twice", priorities: "RESOURCE × RESOURCE (equal — alternative search)", status: "active",
      alternatives: [
        { label: "N-1: backend moves to 8081", outcome: "Evaluating — preflight probing 8081", selected: false },
        { label: "N-2: nginx moves to 8081", outcome: "Candidate — not yet selected", selected: false },
      ],
      resolution: null, rationale: "Awaiting round-1 alternative outcome. Approval stays disabled; max 3 rounds.", round: 1, maxRounds: 3 },
  ],
};

export function conflictsFor(projectId: string): CnpConflict[] {
  return SEED_CONFLICTS[projectId] ?? [];
}

export const SEED_RUNS: RunRecord[] = [
  {
    id: "run-sunny-1", projectId: "proj-sunny", proposalId: null, scenarioKey: "simulated-success",
    status: "succeeded", startedAt: AT("10 08:02"), duration: "14.2s", verification: "pass", simulator: true,
    summary: "Clean negotiate → verify → execute. All 5 services healthy; no rollback.",
    stages: [
      { name: "Preflight", state: "done" }, { name: "Analyze", state: "done" }, { name: "Negotiate", state: "done" },
      { name: "Verify", state: "done" }, { name: "Execute", state: "done" }, { name: "Complete", state: "done" },
    ],
    events: [
      { at: "08:02:01", severity: "info", message: "Preflight passed: localhost target, workspace ready." },
      { at: "08:02:04", severity: "success", message: "CNP: no conflicts; 3 constraints accepted.", ref: "c_port_backend" },
      { at: "08:02:08", severity: "success", message: "Verification gate passed 6/6.", ref: "env-required" },
      { at: "08:02:14", severity: "success", message: "Execution complete: 5/5 services healthy." },
    ],
    logs: ["[simulator] create_network medha-demo … ok", "[simulator] start database … healthy", "[simulator] start backend … healthy", "[simulator] start frontend … healthy"],
    ceg: {
      nodes: [
        { id: "n_network", label: "network · create", state: "success", detail: "No dependencies" },
        { id: "n_database", label: "database · start", state: "success", detail: "Depends on n_network" },
        { id: "n_backend", label: "backend · start", state: "success", detail: "Depends on n_database" },
        { id: "n_frontend", label: "frontend · start", state: "success", detail: "Depends on n_backend" },
      ],
      edges: [
        { from: "n_network", to: "n_database", label: "causal" }, { from: "n_database", to: "n_backend", label: "causal" }, { from: "n_backend", to: "n_frontend", label: "causal" },
      ],
    },
    cig: { changed: ["compose.yaml"], affected: ["backend", "nginx"], paths: [{ from: "compose.yaml", to: "backend", via: "service dependency" }] },
    recovery: null,
  },
  {
    id: "run-vault-verify-1", projectId: "proj-vault", proposalId: "prop-vault-1", scenarioKey: "verification-failure",
    status: "blocked", startedAt: AT("10 11:20"), duration: "6.8s", verification: "fail", simulator: true,
    summary: "Verification gate FAILED on env-required; executor never started (bounded replan proposed).",
    stages: [
      { name: "Preflight", state: "done" }, { name: "Analyze", state: "done" }, { name: "Negotiate", state: "done" },
      { name: "Verify", state: "failed" }, { name: "Execute", state: "skipped" }, { name: "Complete", state: "todo" },
    ],
    events: [
      { at: "11:20:02", severity: "info", message: "Analysis complete: 3 files changed." },
      { at: "11:20:05", severity: "error", message: "Verification FAILED: env-required — DATABASE_URL missing.", ref: "env-required" },
      { at: "11:20:06", severity: "warning", message: "Executor blocked: gate must pass first." },
      { at: "11:22:10", severity: "info", message: "Replan round 1 proposed: inject DATABASE_URL from local env." },
    ],
    logs: ["[verifier] env-required … FAIL (DATABASE_URL missing)", "[executor] blocked: gate FAILED — no CEG nodes written"],
    ceg: { nodes: [], edges: [] },
    cig: { changed: ["compose.yaml", "backend/app/config.py"], affected: ["backend"], paths: [{ from: "backend/app/config.py", to: "backend", via: "env reference" }] },
    recovery: null,
  },
  {
    id: "run-partial-1", projectId: "proj-partial", proposalId: null, scenarioKey: "failed-scoped-recovery",
    status: "recovered", startedAt: AT("08 22:31"), duration: "21.5s", verification: "pass", simulator: true,
    summary: "Backend failed; frontend rolled back; network/database/analytics preserved.",
    stages: [
      { name: "Preflight", state: "done" }, { name: "Analyze", state: "done" }, { name: "Negotiate", state: "done" },
      { name: "Verify", state: "done" }, { name: "Execute", state: "failed" }, { name: "Recover", state: "done" },
    ],
    events: [
      { at: "22:36:10", severity: "error", message: "Backend health check failed after start.", ref: "n_backend" },
      { at: "22:36:11", severity: "warning", message: "Rollback scope: frontend only; 3 services preserved.", ref: "n_frontend" },
      { at: "22:36:14", severity: "success", message: "Scoped recovery complete: partial_recovery." },
    ],
    logs: ["[executor] n_backend … FAILED (health)", "[rollback] n_frontend reversed … ok", "[rollback] preserved: network, database, analytics"],
    ceg: {
      nodes: [
        { id: "n_network", label: "network · create", state: "preserved", detail: "Independent of failure" },
        { id: "n_database", label: "database · start", state: "preserved", detail: "Independent of failure" },
        { id: "n_analytics", label: "analytics · start", state: "preserved", detail: "Independent of failure" },
        { id: "n_backend", label: "backend · start", state: "failed", detail: "Failure origin" },
        { id: "n_frontend", label: "frontend · start", state: "rolled_back", detail: "Dependent on backend" },
      ],
      edges: [
        { from: "n_network", to: "n_database", label: "causal" }, { from: "n_database", to: "n_backend", label: "causal" }, { from: "n_backend", to: "n_frontend", label: "causal" },
      ],
    },
    cig: { changed: ["backend/app/main.py"], affected: ["backend", "frontend"], paths: [{ from: "backend/app/main.py", to: "frontend", via: "api-consumer" }] },
    recovery: {
      origin: "n_backend (health check failed)",
      affected: ["n_backend", "n_frontend"],
      rollbackScope: ["n_frontend"],
      preserved: ["n_network", "n_database", "n_analytics"],
      steps: [
        { label: "Stop frontend (dependent of backend)", state: "done" },
        { label: "Mark backend failed; keep for inspection", state: "done" },
        { label: "Verify preserved services still healthy", state: "done" },
      ],
    },
  },
  {
    id: "run-interrupted-1", projectId: "proj-interrupted", proposalId: null, scenarioKey: "interrupted-run",
    status: "interrupted", startedAt: AT("11 07:15"), duration: "—", verification: "not_run", simulator: false,
    summary: "Event stream disconnected during EXECUTE. Last saved state shown; outcome unknown — reload to reconcile.",
    stages: [
      { name: "Preflight", state: "done" }, { name: "Analyze", state: "done" }, { name: "Negotiate", state: "done" },
      { name: "Verify", state: "done" }, { name: "Execute", state: "active" }, { name: "Complete", state: "todo" },
    ],
    events: [
      { at: "07:15:40", severity: "info", message: "Execute started: database healthy." },
      { at: "07:16:02", severity: "warning", message: "Event stream lost — outcome unknown. Showing last saved state." },
    ],
    logs: ["[executor] database … healthy", "[stream] disconnected — awaiting reconcile"],
    ceg: {
      nodes: [
        { id: "n_network", label: "network · create", state: "success", detail: "Confirmed" },
        { id: "n_database", label: "database · start", state: "success", detail: "Confirmed" },
        { id: "n_backend", label: "backend · start", state: "running", detail: "Unknown — stream lost" },
      ],
      edges: [{ from: "n_network", to: "n_database", label: "causal" }, { from: "n_database", to: "n_backend", label: "causal" }],
    },
    cig: { changed: ["edge/app.py"], affected: ["backend"], paths: [] },
    recovery: null,
  },
  {
    id: "run-metro-1", projectId: "proj-metro", proposalId: null, scenarioKey: "populated-multi-run",
    status: "succeeded", startedAt: AT("09 09:00"), duration: "13.9s", verification: "pass", simulator: true,
    summary: "Clean run; baseline for comparison.", stages: [{ name: "Execute", state: "done" }, { name: "Complete", state: "done" }],
    events: [{ at: "09:00:10", severity: "success", message: "Run completed: all healthy." }], logs: ["[simulator] ok"],
    ceg: { nodes: [{ id: "n_backend", label: "backend · start", state: "success", detail: "" }], edges: [] },
    cig: { changed: [], affected: [], paths: [] }, recovery: null,
  },
  {
    id: "run-metro-2", projectId: "proj-metro", proposalId: null, scenarioKey: "populated-multi-run",
    status: "failed", startedAt: AT("10 09:00"), duration: "7.1s", verification: "fail", simulator: true,
    summary: "Blocked at verification (missing env); comparable definitions to run-metro-1.",
    stages: [{ name: "Verify", state: "failed" }, { name: "Execute", state: "skipped" }],
    events: [{ at: "09:00:05", severity: "error", message: "Verification FAILED: env-required." }], logs: ["[verifier] FAIL"],
    ceg: { nodes: [], edges: [] }, cig: { changed: [], affected: [], paths: [] }, recovery: null,
  },
  {
    id: "run-metro-3", projectId: "proj-metro", proposalId: null, scenarioKey: "populated-multi-run",
    status: "recovered", startedAt: AT("11 06:58"), duration: "19.8s", verification: "pass", simulator: true,
    summary: "Partial failure with scoped recovery; same measurement definitions as metro-1/2.",
    stages: [{ name: "Execute", state: "failed" }, { name: "Recover", state: "done" }],
    events: [{ at: "06:58:10", severity: "warning", message: "Scoped recovery: 1 rolled back, 3 preserved." }], logs: ["[rollback] scoped ok"],
    ceg: { nodes: [{ id: "n_backend", label: "backend · start", state: "failed", detail: "origin" }], edges: [] },
    cig: { changed: [], affected: [], paths: [] },
    recovery: { origin: "n_backend", affected: ["n_backend", "n_frontend"], rollbackScope: ["n_frontend"], preserved: ["n_network", "n_database", "n_analytics"], steps: [{ label: "Reverse frontend", state: "done" }] },
  },
];

export const SEED_EVALS: Record<string, EvalSuite> = {
  "proj-evalempty": { id: "eval-empty", name: "No suites yet", scenarios: 0, status: "empty", results: [], failurePatterns: [], note: "Empty evaluation history. Run the backend CNP/CEG runners or start demo runs to populate comparable results." },
  "proj-metro": {
    id: "eval-metro", name: "Metro weekly comparison", scenarios: 3, status: "complete",
    results: [
      { scenario: "metro-1 · clean", outcome: "succeeded", verification: "pass 6/6", recovery: "n/a" },
      { scenario: "metro-2 · missing env", outcome: "blocked", verification: "fail env-required", recovery: "n/a — executor never started" },
      { scenario: "metro-3 · backend fault", outcome: "recovered", verification: "pass 6/6", recovery: "1 rolled back · 3 preserved" },
    ],
    failurePatterns: [
      { category: "missing-env blocks gate", count: 1 },
      { category: "backend fault → scoped rollback", count: 1 },
    ],
    note: "Compared runs share definitions: same gate checklist and same 5-service graph. Do not compare across different gates.",
  },
};

export function evalFor(projectId: string): EvalSuite {
  return SEED_EVALS[projectId] ?? {
    id: `eval-${projectId}`, name: "Project evaluation", scenarios: 0, status: "empty", results: [],
    failurePatterns: [], note: "No evaluation data for this project yet. Results appear after comparable runs share the same measurement definitions.",
  };
}
