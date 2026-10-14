"use client";

import { useRef, useState } from "react";
import {
  createProject,
  createProjectRun,
  deleteProject,
  verifyProject,
} from "@/lib/api/client";
import { Dialog } from "@/components/ui/primitives";

/**
 * Compact GitHub connection form: URL required, name and branch optional.
 *
 * One submit does create → live readability check → first analysis, then
 * closes and refreshes so the new card shows the real running state.
 * The modal stays open with an actionable error on any failure, and only
 * verified connections are kept — an unreachable repository never persists
 * as a fake connection.
 */
export function ConnectRepoDialog({ onClose, onDone }: {
  onClose: () => void;
  onDone: () => void;
}) {
  const [repository, setRepository] = useState("");
  const [name, setName] = useState("");
  const [branch, setBranch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [connectedName, setConnectedName] = useState<string | null>(null);
  // Ref guard: React state updates async, so rapid double-clicks could both
  // pass the `busy` check before either sets it. The ref closes that gap.
  const submitting = useRef(false);

  function actionable(message: string, code?: string): string {
    if (code === "PROJECT_EXISTS") {
      return "This repository is already connected in this workspace. Search the project list for it instead of connecting again.";
    }
    if (code === "NON_GITHUB_REPOSITORY") {
      return "V1 supports github.com repositories only.";
    }
    if (code === "INVALID_REPOSITORY_REF") {
      return "Use 'owner/name' or a full github.com URL (e.g. https://github.com/octo/demo).";
    }
    if (code === "INVALID_BRANCH") {
      return "That branch name is not acceptable. Leave it blank to auto-detect the default branch.";
    }
    if (code === "DEPLOYMENT_BUSY") {
      return `The repository is connected, but another analysis is already running (V1 runs one at a time). Close this dialog and use “Re-analyze” on the new card once it finishes.`;
    }
    return message;
  }

  async function submit() {
    if (busy || submitting.current) return;
    const repoInput = repository.trim();
    if (repoInput.length < 3 || !repoInput.includes("/")) {
      setError("Enter a GitHub repository as 'owner/name' or a github.com URL.");
      return;
    }
    submitting.current = true;
    setBusy(true);
    setError(null);
    let projectId: string | null = null;
    try {
      const created = await createProject({
        repository: repoInput,
        ...(name.trim() ? { name: name.trim() } : {}),
        ...(branch.trim() ? { branch: branch.trim() } : {}),
      });
      projectId = created.project_id;
      const verification = await verifyProject(created.project_id);
      if (!verification.reachable) {
        // Not a real connection — remove the pending row so a corrected
        // retry does not collide with it, then explain what to do.
        try {
          await deleteProject(created.project_id);
        } catch {
          /* cleanup is best-effort; the error below is what matters */
        }
        projectId = null;
        setError(
          verification.reason ??
            "Repository is unreachable or private. Private repositories need a configured GitHub App; public ones need network access from this host.",
        );
        return;
      }
      await createProjectRun(created.project_id, {});
      setConnectedName(created.name);
      onDone();
      onClose();
    } catch (err) {
      const code = err instanceof Error && "code" in err
        ? String((err as { code?: unknown }).code ?? "")
        : "";
      const message = err instanceof Error ? err.message : "Could not connect this repository.";
      // A verified connection whose first run could not start is still a
      // real connection: keep it, refresh the list, and let the user close.
      if (projectId && (code === "DEPLOYMENT_BUSY" || code === "PROJECT_NOT_CONNECTED")) {
        setConnectedName(repository.trim());
        setError(actionable(message, code));
        onDone();
        return;
      }
      setError(actionable(message, code || undefined));
      // Reconnect races and already-connected repos resolve to the existing
      // project server-side: refresh the authoritative list so the one
      // correct card is visible instead of manufacturing local state.
      if (code === "PROJECT_EXISTS") {
        onDone();
      }
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  const connectedKeepOpen = connectedName !== null;

  return (
    <Dialog
      title="Connect GitHub repository"
      confirmLabel={busy ? "Connecting…" : connectedKeepOpen ? "Done" : "Connect"}
      confirmDisabled={busy}
      onConfirm={() => {
        if (busy || submitting.current) return;
        if (connectedKeepOpen) onClose();
        else void submit();
      }}
      onCancel={onClose}
      body={
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!busy && !submitting.current && !connectedKeepOpen) void submit();
          }}
        >
          <div>
            <label htmlFor="cr-repo" className="medha-label">GitHub repository *</label>
            <input
              id="cr-repo"
              className="field-input mt-1"
              value={repository}
              onChange={(e) => setRepository(e.target.value)}
              placeholder="owner/name or https://github.com/owner/name"
              autoComplete="off"
              disabled={busy || connectedKeepOpen}
            />
          </div>
          <div>
            <label htmlFor="cr-name" className="medha-label">Connection name <span className="font-normal">(optional)</span></label>
            <input
              id="cr-name"
              className="field-input mt-1"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Defaults to the repository name"
              autoComplete="off"
              disabled={busy || connectedKeepOpen}
            />
          </div>
          <div>
            <label htmlFor="cr-branch" className="medha-label">Branch <span className="font-normal">(optional)</span></label>
            <input
              id="cr-branch"
              className="field-input mt-1"
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
              placeholder="Auto-detect default branch"
              autoComplete="off"
              disabled={busy || connectedKeepOpen}
            />
            <p className="mt-1 text-[12px] text-medha-secondary">
              Public repositories only in V1. Stack and manifests are inferred
              automatically during analysis — nothing else to configure. Access
              is proven by a live readability check; never paste a token.
            </p>
          </div>
          {error ? (
            <p role="alert" className="rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-[13px] text-medha-danger">{error}</p>
          ) : null}
          {connectedKeepOpen && !error ? (
            <p role="status" className="rounded-lg border border-medha-success/30 bg-medha-success-soft px-3 py-2 text-[13px] text-medha-success">
              Connected as {connectedName}.
            </p>
          ) : null}
        </form>
      }
    />
  );
}
