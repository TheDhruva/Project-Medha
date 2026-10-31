"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, GitBranch, Loader2 } from "lucide-react";
import {
  createProject,
  createProjectRun,
  deleteProject,
  fetchProjects,
  validateRepository,
  verifyProject,
  type ValidateRepositoryResponse,
} from "@/lib/api/client";
import { Dialog } from "@/components/ui/primitives";

type ValidationState =
  | { status: "idle" }
  | { status: "validating" }
  | { status: "found"; data: ValidateRepositoryResponse }
  | { status: "error"; message: string };

/**
 * Premium GitHub repository onboarding workflow:
 * - Single required input for repository URL or owner/name.
 * - Automatic real-time validation and branch retrieval via git ls-remote.
 * - Searchable branch selector pre-selecting the verified default branch.
 * - Clean, actionable error states and double-submission prevention.
 */
export function ConnectRepoDialog({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const router = useRouter();
  const [repository, setRepository] = useState("");
  const [branch, setBranch] = useState("");
  const [validation, setValidation] = useState<ValidationState>({ status: "idle" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Debounced repository validation and branch retrieval
  useEffect(() => {
    const trimmed = repository.trim();
    if (!trimmed || !trimmed.includes("/") || trimmed.length < 3) {
      if (abortControllerRef.current) abortControllerRef.current.abort();
      setValidation({ status: "idle" });
      setBranch("");
      return;
    }

    if (abortControllerRef.current) abortControllerRef.current.abort();
    const ac = new AbortController();
    abortControllerRef.current = ac;

    setValidation({ status: "validating" });
    setError(null);

    const timer = setTimeout(async () => {
      try {
        const res = await validateRepository(trimmed, ac.signal);
        setValidation({ status: "found", data: res });
        setBranch(res.default_branch || (res.branches[0] ?? "main"));
      } catch (err: unknown) {
        if (ac.signal.aborted) return;
        const code =
          err instanceof Error && "code" in err
            ? String((err as { code?: unknown }).code ?? "")
            : "";
        let msg = "Could not validate this repository.";
        if (code === "REPO_NOT_FOUND") {
          msg = "Repository not found or private. Ensure the repository exists and is accessible.";
        } else if (code === "AUTH_REQUIRED" || code === "PRIVATE_UNSUPPORTED") {
          msg = "Access denied or authentication required. Private repositories require a configured GitHub App.";
        } else if (code === "RATE_LIMITED") {
          msg = "GitHub API rate limit exceeded. Please try again later.";
        } else if (code === "NETWORK_ERROR" || code === "GIT_TIMEOUT") {
          msg = "Network error connecting to repository. Check connectivity and retry.";
        } else if (err instanceof Error && err.message) {
          msg = err.message;
        }
        setValidation({ status: "error", message: msg });
        setBranch("");
      }
    }, 350);

    return () => {
      clearTimeout(timer);
      ac.abort();
    };
  }, [repository]);

  function actionable(message: string, code?: string): string {
    if (code === "PROJECT_EXISTS") {
      return "This repository is already connected. Taking you to its project page…";
    }
    if (code === "NON_GITHUB_REPOSITORY") {
      return "MEDHA currently supports github.com repositories.";
    }
    if (code === "INVALID_REPOSITORY_REF") {
      return "Enter a valid repository as 'owner/name' or a github.com URL (e.g. https://github.com/octo/demo).";
    }
    if (code === "INVALID_BRANCH") {
      return "That branch name is invalid. Leave it blank to automatically use the default branch.";
    }
    if (code === "DEPLOYMENT_BUSY") {
      return "The repository was added, but another analysis is already active. You can review the repository now.";
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
      const selectedBranch =
        branch.trim() ||
        (validation.status === "found" ? validation.data.default_branch : undefined);

      const created = await createProject({
        repository: repoInput,
        ...(selectedBranch ? { branch: selectedBranch } : {}),
      });
      projectId = created.project_id;

      const verification = await verifyProject(created.project_id);
      if (!verification.reachable) {
        if (!created.existed) {
          try {
            await deleteProject(created.project_id);
          } catch {
            /* best effort cleanup */
          }
          projectId = null;
        }
        setError(
          verification.reason ??
            "Repository is unreachable or private. Ensure the repository exists and is accessible.",
        );
        return;
      }

      let targetUrl = `/projects/${created.project_id}`;
      try {
        const run = await createProjectRun(created.project_id, {});
        if (run && run.deployment_id) {
          targetUrl = `/projects/${created.project_id}/runs/${run.deployment_id}`;
        }
      } catch (runErr) {
        console.warn("Could not start initial run immediately:", runErr);
      }

      onDone();
      onClose();
      router.push(targetUrl);
    } catch (err) {
      const code =
        err instanceof Error && "code" in err
          ? String((err as { code?: unknown }).code ?? "")
          : "";
      const message =
        err instanceof Error ? err.message : "Could not connect this repository.";

      if (code === "PROJECT_EXISTS") {
        try {
          const res = await fetchProjects();
          const target = repoInput.toLowerCase();
          const existing = res.projects.find((p) => {
            const pRepo = `${p.repo_owner}/${p.repo_name}`.toLowerCase();
            return (
              target.includes(pRepo) ||
              p.canonical_url.toLowerCase().includes(target)
            );
          });
          if (existing) {
            onDone();
            onClose();
            router.push(`/projects/${existing.project_id}`);
            return;
          }
        } catch {
          /* fallback */
        }
      }

      setError(actionable(message, code || undefined));
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  const isValidating = validation.status === "validating";
  const hasBranchData = validation.status === "found";

  return (
    <Dialog
      title="Connect repository"
      confirmLabel={busy ? "Connecting…" : isValidating ? "Validating…" : "Connect repository"}
      confirmDisabled={busy || isValidating || !repository.trim() || validation.status === "error"}
      onConfirm={() => {
        if (busy || submitting.current) return;
        void submit();
      }}
      onCancel={onClose}
      body={
        <form
          className="space-y-3.5"
          onSubmit={(e) => {
            e.preventDefault();
            if (!busy && !submitting.current) void submit();
          }}
        >
          <div>
            <label htmlFor="cr-repo" className="medha-label">
              GitHub repository <span className="text-medha-danger">*</span>
            </label>
            <div className="relative mt-1">
              <input
                id="cr-repo"
                className="field-input pr-8"
                value={repository}
                onChange={(e) => setRepository(e.target.value)}
                placeholder="owner/name or https://github.com/owner/name"
                autoComplete="off"
                disabled={busy}
                autoFocus
              />
              {isValidating ? (
                <div className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-medha-accent">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                </div>
              ) : null}
            </div>
          </div>

          {isValidating ? (
            <div className="flex items-center gap-2 py-0.5 text-[12px] text-medha-secondary">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-medha-accent shrink-0" aria-hidden />
              <span>Validating repository & retrieving branches…</span>
            </div>
          ) : null}

          {hasBranchData ? (
            <div className="space-y-3">
              <div className="flex items-center gap-1.5 py-0.5 text-[12px] text-medha-success">
                <Check className="h-3.5 w-3.5 text-medha-success shrink-0" aria-hidden />
                <span>
                  Repository verified: <span className="font-semibold">{validation.data.owner}/{validation.data.name}</span>
                </span>
              </div>

              <div>
                <label htmlFor="cr-branch" className="medha-label flex items-center justify-between">
                  <span>Branch</span>
                  <span className="text-[11px] font-normal text-medha-tertiary">
                    {validation.data.branches.length} {validation.data.branches.length === 1 ? "branch" : "branches"}
                  </span>
                </label>
                <div className="relative mt-1">
                  <select
                    id="cr-branch"
                    value={branch}
                    onChange={(e) => setBranch(e.target.value)}
                    disabled={busy}
                    className="field-input pr-8"
                  >
                    {validation.data.branches.map((b) => (
                      <option key={b} value={b}>
                        {b} {b === validation.data.default_branch ? "(default)" : ""}
                      </option>
                    ))}
                  </select>
                  <div className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-medha-tertiary">
                    <GitBranch className="h-3.5 w-3.5" aria-hidden />
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {validation.status === "error" ? (
            <p
              role="alert"
              className="rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-[12.5px] text-medha-danger"
            >
              {validation.message}
            </p>
          ) : null}

          {error ? (
            <p
              role="alert"
              className="rounded-lg border border-medha-danger/30 bg-medha-danger-soft px-3 py-2 text-[12.5px] text-medha-danger"
            >
              {error}
            </p>
          ) : null}
        </form>
      }
    />
  );
}
