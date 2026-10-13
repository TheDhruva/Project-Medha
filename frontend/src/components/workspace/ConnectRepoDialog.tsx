"use client";

import { useState } from "react";
import {
  createProject,
  createProjectRun,
  verifyProject,
  type Project,
} from "@/lib/api/client";
import { Button, Dialog } from "@/components/ui/primitives";

/**
 * Connect a GitHub repository to MEDHA as a project-scoped connection.
 *
 * A repository reference is configuration only — this dialog proves
 * readability with `git ls-remote` (verify step) and says so honestly when
 * the repository is unreachable or private. Private repositories stay
 * unsupported until a GitHub App exists; they are never accepted via pasted
 * tokens (the backend rejects embedded credentials outright).
 */
export function ConnectRepoDialog({ onClose, onDone }: {
  onClose: () => void;
  onDone: () => void;
}) {
  const [name, setName] = useState("");
  const [repository, setRepository] = useState("");
  const [branch, setBranch] = useState("main");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [project, setProject] = useState<Project | null>(null);
  const [verified, setVerified] = useState<null | { reachable: boolean; reason?: string }>(null);
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);

  async function connect() {
    if (saving) return;
    if (name.trim().length < 1) {
      setError("Give the connection a name.");
      return;
    }
    if (repository.trim().length < 3 || !repository.includes("/")) {
      setError("Repository must look like 'owner/name' or a github.com URL.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await createProject({
        name: name.trim(),
        repository: repository.trim(),
        branch: branch.trim() || "main",
      });
      setProject(created);
      const result = await verifyProject(created.project_id);
      setProject(result.project);
      setVerified({ reachable: result.reachable, reason: result.reason });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect this repository.");
    } finally {
      setSaving(false);
    }
  }

  async function startFirstRun() {
    if (!project) return;
    setRunning(true);
    setError(null);
    try {
      const run = await createProjectRun(project.project_id, {});
      setRunId(run.deployment_id);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start analysis.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <Dialog
      title="Connect GitHub repository"
      confirmLabel={saving ? "Connecting…" : project ? "Done" : "Connect + verify"}
      confirmDisabled={saving || running}
      onConfirm={() => void (project || saving ? onClose() : connect())}
      onCancel={onClose}
      body={
        <div className="space-y-3">
          <div>
            <label htmlFor="cr-name" className="medha-label">Connection name</label>
            <input
              id="cr-name" className="field-input mt-1" value={name}
              onChange={(e) => setName(e.target.value)} placeholder="My service"
              disabled={project !== null}
            />
          </div>
          <div>
            <label htmlFor="cr-repo" className="medha-label">GitHub repository</label>
            <input
              id="cr-repo" className="field-input mt-1" value={repository}
              onChange={(e) => setRepository(e.target.value)} placeholder="owner/name"
              disabled={project !== null}
            />
            <p className="mt-1 text-[12px] text-medha-secondary">
              Public repositories only in V1. This registers configuration — access is
              proven by a live readability check, never by pasting a token.
            </p>
          </div>
          <div>
            <label htmlFor="cr-branch" className="medha-label">Watched branch</label>
            <input
              id="cr-branch" className="field-input mt-1" value={branch}
              onChange={(e) => setBranch(e.target.value)} placeholder="main"
              disabled={project !== null}
            />
          </div>
          {error ? (
            <p role="alert" className="rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-[13px] text-medha-danger">{error}</p>
          ) : null}
          {project && verified ? (
            <div
              role="status"
              className={`rounded-lg border px-3 py-2 text-[13px] ${verified.reachable
                ? "border-medha-success/30 bg-medha-success-soft text-medha-success"
                : "border-medha-danger/30 bg-medha-danger-soft text-medha-danger"}`}
            >
              {verified.reachable ? (
                <>Connected — repository is readable. Pushes to {project.branch} will trigger approval-gated analysis.</>
              ) : (
                <>Not connected: {verified.reason ?? "repository unreachable or private."}</>
              )}
            </div>
          ) : null}
          {project && verified?.reachable && !runId ? (
            <Button variant="secondary" onClick={() => void startFirstRun()} loading={running}>
              {running ? "Starting…" : "Start first analysis now"}
            </Button>
          ) : null}
          {runId ? (
            <p role="status" className="text-[13px] text-medha-success">
              Analysis started ({runId}). Watch it under Runs; pushes will create approval proposals.
            </p>
          ) : null}
        </div>
      }
    />
  );
}
