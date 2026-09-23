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
