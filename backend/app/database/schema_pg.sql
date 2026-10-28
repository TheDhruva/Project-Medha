CREATE TABLE IF NOT EXISTS deployments (
    seq BIGSERIAL PRIMARY KEY,
    deployment_id TEXT UNIQUE NOT NULL,
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
    pr_number INTEGER,
    is_demo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    seq BIGSERIAL PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,
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
    seq BIGSERIAL PRIMARY KEY,
    clerk_sub TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    seq BIGSERIAL PRIMARY KEY,
    delivery_id TEXT UNIQUE NOT NULL,
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
    seq BIGSERIAL PRIMARY KEY,
    proposal_id TEXT UNIQUE NOT NULL,
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

CREATE INDEX IF NOT EXISTS idx_proposals_deployment
    ON proposals (deployment_id);

CREATE TABLE IF NOT EXISTS projects (
    seq BIGSERIAL PRIMARY KEY,
    project_id TEXT UNIQUE NOT NULL,
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
    baseline_sha TEXT,
    baseline_at TEXT,
    last_full_scan_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_owner_repo
    ON projects (owner_sub, repository);

CREATE INDEX IF NOT EXISTS idx_projects_repository
    ON projects (repository);

-- Known pull requests per connected project (webhook-maintained).
CREATE TABLE IF NOT EXISTS pull_requests (
    seq BIGSERIAL PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT '',
    repository TEXT NOT NULL,
    number INTEGER NOT NULL,
    base_ref TEXT,
    base_sha TEXT,
    head_ref TEXT,
    head_sha TEXT,
    state TEXT NOT NULL DEFAULT 'open',
    last_decision_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, repository, number)
);

CREATE INDEX IF NOT EXISTS idx_pull_requests_head
    ON pull_requests (project_id, head_sha);

CREATE TABLE IF NOT EXISTS jobs (
    seq BIGSERIAL PRIMARY KEY,
    job_id TEXT UNIQUE NOT NULL,
    delivery_id TEXT UNIQUE,
    project_id TEXT,
    repository TEXT NOT NULL,
    branch TEXT NOT NULL DEFAULT 'main',
    base_sha TEXT,
    target_sha TEXT NOT NULL,
    seq_num INTEGER NOT NULL DEFAULT 0,
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
    ON jobs (repository, branch, seq_num);
CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created
    ON jobs (status, created_at);

CREATE TABLE IF NOT EXISTS commits (
    seq BIGSERIAL PRIMARY KEY,
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
    UNIQUE (project_id, sha)
);

CREATE INDEX IF NOT EXISTS idx_commits_project_time
    ON commits (project_id, committed_at);

CREATE TABLE IF NOT EXISTS scores (
    seq BIGSERIAL PRIMARY KEY,
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
    UNIQUE (run_id, score_name)
);

CREATE INDEX IF NOT EXISTS idx_scores_project_sha
    ON scores (project_id, target_sha);

CREATE TABLE IF NOT EXISTS analysis_cache (
    seq BIGSERIAL PRIMARY KEY,
    cache_key TEXT UNIQUE NOT NULL,
    project_id TEXT,
    kind TEXT NOT NULL,
    inputs_hash TEXT NOT NULL,
    target_sha TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);

-- Persistent finding ledger with stable identity and explicit lifecycle.
-- status: detected | under_investigation | confirmed | rejected |
--         accepted_risk | fixed_unverified | resolved | reopened
CREATE TABLE IF NOT EXISTS findings (
    seq BIGSERIAL PRIMARY KEY,
    finding_id TEXT UNIQUE NOT NULL,
    fingerprint TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT '',
    repository TEXT NOT NULL DEFAULT '',
    deployment_id TEXT,
    source TEXT NOT NULL,
    rule_id TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'unknown',
    severity TEXT NOT NULL DEFAULT 'medium',
    confidence TEXT NOT NULL DEFAULT 'medium',
    path TEXT,
    line INTEGER,
    message TEXT NOT NULL DEFAULT '',
    explanation TEXT,
    remediation TEXT,
    status TEXT NOT NULL DEFAULT 'detected',
    verification_status TEXT NOT NULL DEFAULT 'unverified',
    first_seen_sha TEXT,
    last_seen_sha TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    history_json TEXT NOT NULL DEFAULT '[]',
    is_demo INTEGER NOT NULL DEFAULT 0,
    UNIQUE (project_id, repository, fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_findings_project_status
    ON findings (project_id, status);
CREATE INDEX IF NOT EXISTS idx_findings_deployment
    ON findings (deployment_id);
