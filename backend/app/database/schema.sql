CREATE TABLE IF NOT EXISTS deployments (
    deployment_id TEXT PRIMARY KEY,
    repository_url TEXT NOT NULL,
    mode TEXT NOT NULL,
    scenario TEXT,
    target_host TEXT NOT NULL,
    target_port INTEGER NOT NULL,
    intent TEXT,
    base_revision TEXT,
    target_revision TEXT,
    status TEXT NOT NULL,
    current_stage TEXT,
    explain_simple TEXT,
    explain_technical TEXT,
    error_summary TEXT,
    result_json TEXT,
    constraints_json TEXT,
    negotiation_json TEXT,
    verification_json TEXT,
    critic_json TEXT,
    graph_json TEXT,
    rollback_json TEXT,
    change_intel_json TEXT,
    ai_json TEXT,
    owner_sub TEXT,
    project_id TEXT,
    is_demo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    deployment_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    ts TEXT NOT NULL,
    stage TEXT,
    message TEXT NOT NULL,
    status TEXT,
    level TEXT NOT NULL DEFAULT 'info',
    is_demo INTEGER NOT NULL DEFAULT 1,
    data_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (deployment_id) REFERENCES deployments(deployment_id)
);

CREATE INDEX IF NOT EXISTS idx_events_deployment_ts
    ON events (deployment_id, ts);

-- Perf (measured filters): owner/status listing, recovery status scans.
CREATE INDEX IF NOT EXISTS idx_deployments_owner_status
    ON deployments (owner_sub, status);
CREATE INDEX IF NOT EXISTS idx_deployments_status
    ON deployments (status);

CREATE TABLE IF NOT EXISTS users (
    clerk_sub TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    delivery_id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'github',
    repository TEXT NOT NULL,
    ref TEXT,
    sha TEXT,
    event TEXT,
    status TEXT NOT NULL DEFAULT 'received',
    proposal_id TEXT,
    received_at TEXT NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    repository TEXT NOT NULL,
    branch TEXT NOT NULL,
    base_sha TEXT,
    target_sha TEXT NOT NULL,
    deployment_id TEXT,
    plan_hash TEXT,
    plan_json TEXT,
    push_json TEXT,
    project_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_by TEXT,
    created_at TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT,
    execution_id TEXT,
    idempotency_key TEXT UNIQUE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_proposals_repo_branch
    ON proposals (repository, branch);

-- Perf: get_by_deployment + approve/decision paths filter by deployment_id.
CREATE INDEX IF NOT EXISTS idx_proposals_deployment
    ON proposals (deployment_id);

-- Project-scoped repository connections (multi-user, repository-agnostic).
-- A project binds one owner's view of one GitHub repository + branch.
-- No credentials are stored here: readability is proven by git ls-remote
-- (verify endpoint) and by successful SHA checkout at analysis time.
-- connection_status: pending | connected | failed | disconnected
-- visibility: unverified | public | private_unsupported
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    owner_sub TEXT NOT NULL,
    name TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'github',
    repo_owner TEXT NOT NULL,
    repo_name TEXT NOT NULL,
    repository TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    branch TEXT NOT NULL DEFAULT 'main',
    visibility TEXT NOT NULL DEFAULT 'unverified',
    connection_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_owner_repo
    ON projects (owner_sub, repository);

CREATE INDEX IF NOT EXISTS idx_projects_repository
    ON projects (repository);
