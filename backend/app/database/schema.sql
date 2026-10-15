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
CREATE INDEX IF NOT EXISTS idx_deployments_project
    ON deployments (project_id);
CREATE INDEX IF NOT EXISTS idx_deployments_project_status
    ON deployments (project_id, status);
CREATE INDEX IF NOT EXISTS idx_events_deployment
    ON events (deployment_id);

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
    deploy_target TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_owner_repo
    ON projects (owner_sub, repository);
CREATE INDEX IF NOT EXISTS idx_projects_repository
    ON projects (repository);

-- Durable analysis jobs (Phase 4). The database is the source of truth;
-- any in-process queue only wakes workers. Status: queued | running |
-- succeeded | failed | cancelled | superseded | dead_letter.
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    delivery_id TEXT UNIQUE,
    project_id TEXT,
    repository TEXT NOT NULL,
    branch TEXT NOT NULL DEFAULT 'main',
    base_sha TEXT,
    target_sha TEXT NOT NULL,
    seq INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    deployment_id TEXT,
    last_error TEXT,
    not_before TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_repo_branch_seq
    ON jobs (repository, branch, seq);
CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created
    ON jobs (status, created_at);

-- Commit history metadata (Phase 7). Enough to render the graph without
-- re-cloning; diff summaries attach per commit on demand. summary/files
-- are recorded at analysis time from the pinned checkout (deterministic,
-- evidence-based); NULL summary means not yet summarized, never fabricated.
CREATE TABLE IF NOT EXISTS commits (
    project_id TEXT NOT NULL,
    sha TEXT NOT NULL,
    parents_json TEXT NOT NULL DEFAULT '[]',
    author TEXT,
    committed_at TEXT,
    message TEXT,
    branch TEXT,
    recorded_at TEXT NOT NULL,
    summary TEXT,
    files_json TEXT NOT NULL DEFAULT '[]',
    added INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    deployment_id TEXT,
    PRIMARY KEY (project_id, sha)
);

CREATE INDEX IF NOT EXISTS idx_commits_project_time
    ON commits (project_id, committed_at);

-- Versioned score snapshots (Phase 6). One row per (run, score_name).
-- value_null means unavailable/insufficient evidence — never success.
CREATE TABLE IF NOT EXISTS scores (
    run_id TEXT NOT NULL,
    score_name TEXT NOT NULL,
    value REAL,
    value_null INTEGER NOT NULL DEFAULT 0,
    version TEXT NOT NULL DEFAULT 'v1',
    computed_at TEXT NOT NULL,
    inputs_hash TEXT NOT NULL,
    target_sha TEXT NOT NULL,
    project_id TEXT,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (run_id, score_name)
);

CREATE INDEX IF NOT EXISTS idx_scores_project_sha
    ON scores (project_id, target_sha);

-- Incremental analysis cache metadata (Phase 5). Payloads stay in the
-- existing artifact blobs; this table tracks validity for reuse.
CREATE TABLE IF NOT EXISTS analysis_cache (
    cache_key TEXT PRIMARY KEY,
    project_id TEXT,
    kind TEXT NOT NULL,
    inputs_hash TEXT NOT NULL,
    target_sha TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
