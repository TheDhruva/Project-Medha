"use client";

import { useEffect, useState } from "react";
import {
  Check,
  AlertCircle,
  ArrowRight,
  ExternalLink,
  GitBranch,
  GitPullRequest,
  Loader2,
  RefreshCw,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  applyAndVerifyRepair,
  deliverRepair,
  fetchRepairPlan,
  type FindingView,
  type RepairDelivery,
  type RepairPlan,
  type RepairVerification,
} from "@/lib/api/client";
import { Badge, Button } from "@/components/ui/primitives";
import { severityTone } from "@/components/workspace/FindingsPanel";

interface RepairReviewModalProps {
  projectId: string;
  finding: FindingView;
  onClose: () => void;
  onResolved: () => void;
}

export function RepairReviewModal({
  projectId,
  finding,
  onClose,
  onResolved,
}: RepairReviewModalProps) {
  const [loadingPlan, setLoadingPlan] = useState(true);
  const [plan, setPlan] = useState<RepairPlan | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);

  const [verifying, setVerifying] = useState(false);
  const [verification, setVerification] = useState<RepairVerification | null>(null);
  const [branchName, setBranchName] = useState<string | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);

  const [delivering, setDelivering] = useState(false);
  const [delivery, setDelivery] = useState<RepairDelivery | null>(null);
  const [deliverError, setDeliverError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoadingPlan(true);
    setPlanError(null);

    fetchRepairPlan(projectId, finding.finding_id)
      .then((p) => {
        if (active) {
          setPlan(p);
          setLoadingPlan(false);
        }
      })
      .catch((err) => {
        if (active) {
          setPlanError(err instanceof Error ? err.message : "Could not generate automated repair plan.");
          setLoadingPlan(false);
        }
      });

    return () => {
      active = false;
    };
  }, [projectId, finding.finding_id]);

  async function handleVerify() {
    setVerifying(true);
    setVerifyError(null);
    try {
      const res = await applyAndVerifyRepair(projectId, finding.finding_id);
      setVerification(res.verification);
      setBranchName(res.branch_name);
    } catch (err) {
      setVerifyError(err instanceof Error ? err.message : "Sandbox verification failed.");
    } finally {
      setVerifying(false);
    }
  }

  async function handleDeliver() {
    setDelivering(true);
    setDeliverError(null);
    try {
      const res = await deliverRepair(projectId, finding.finding_id, branchName || undefined);
      setDelivery(res);
      if (res.delivered) {
        onResolved();
      }
    } catch (err) {
      setDeliverError(err instanceof Error ? err.message : "Delivery failed.");
    } finally {
      setDelivering(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="repair-modal-title"
    >
      <div
        className="absolute inset-0"
        style={{ backgroundColor: "rgba(36, 39, 43, 0.45)" }}
        onClick={onClose}
        aria-hidden
      />
      <div className="relative flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl border border-medha-border bg-white shadow-medha">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-medha-border p-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Badge tone={severityTone(finding.severity)}>{finding.severity}</Badge>
              <span className="medha-mono text-xs font-semibold text-medha-text">
                {finding.rule_id}
              </span>
              <span className="text-sm font-semibold text-medha-text">
                Automated Issue Remediation
              </span>
            </div>
            <p className="medha-mono text-xs text-medha-tertiary">
              {finding.path}
              {finding.line != null ? `:${finding.line}` : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-medha-tertiary hover:bg-medha-muted hover:text-medha-text"
            aria-label="Close dialog"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Finding Explanation */}
          <div className="rounded-lg border border-medha-border bg-medha-surface-muted p-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-medha-secondary">
              Problem Description
            </h3>
            <p className="mt-1 text-sm text-medha-text">{finding.message}</p>
            {finding.explanation ? (
              <p className="mt-1 text-xs text-medha-secondary">{finding.explanation}</p>
            ) : null}
          </div>

          {/* Loading or Error */}
          {loadingPlan ? (
            <div className="flex items-center justify-center py-8 text-medha-secondary">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              <span>Analyzing code and generating targeted patch…</span>
            </div>
          ) : planError ? (
            <div className="rounded-lg border border-medha-danger/30 bg-medha-danger-soft p-3 text-sm text-medha-danger">
              <p className="font-semibold">Automated plan unavailable</p>
              <p className="mt-1 text-xs">{planError}</p>
            </div>
          ) : plan ? (
            <div className="space-y-4">
              {/* Proposed Solution */}
              <div>
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-medha-secondary">
                    Proposed Solution
                  </h3>
                  {plan.diff_hash ? (
                    <span className="medha-mono text-[10px] text-medha-tertiary">
                      Diff Hash: {plan.diff_hash.slice(0, 10)}
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 text-sm font-medium text-medha-text">{plan.title}</p>
                <p className="text-xs text-medha-secondary">{plan.message}</p>
              </div>

              {/* Diff Viewer */}
              {plan.diff_unified ? (
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-medha-secondary">
                    Review Proposed Code Changes
                  </h3>
                  <pre className="mt-1.5 max-h-60 overflow-x-auto rounded-lg border border-medha-border bg-slate-900 p-3 font-mono text-[12px] leading-relaxed text-slate-100">
                    {plan.diff_unified.split("\n").map((line, idx) => {
                      const isAdd = line.startsWith("+") && !line.startsWith("+++");
                      const isDel = line.startsWith("-") && !line.startsWith("---");
                      const isHunk = line.startsWith("@@");
                      return (
                        <div
                          key={idx}
                          className={
                            isAdd
                              ? "bg-emerald-950/70 text-emerald-300"
                              : isDel
                              ? "bg-rose-950/70 text-rose-300"
                              : isHunk
                              ? "text-sky-400 font-semibold"
                              : "text-slate-300"
                          }
                        >
                          {line}
                        </div>
                      );
                    })}
                  </pre>
                </div>
              ) : (
                <div className="rounded-lg border border-medha-border bg-amber-50 p-3 text-xs text-amber-800">
                  {plan.message || "Manual code changes required for this finding category."}
                </div>
              )}

              {/* Sandbox Verification Result */}
              {verifying ? (
                <div className="flex items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 p-3 text-xs text-sky-800">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>Applying patch in isolated git worktree sandbox and re-testing rule…</span>
                </div>
              ) : verifyError ? (
                <div className="rounded-lg border border-medha-danger/30 bg-medha-danger-soft p-3 text-xs text-medha-danger">
                  <p className="font-semibold">Sandbox Verification Failed</p>
                  <p className="mt-1">{verifyError}</p>
                </div>
              ) : verification ? (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900 space-y-1.5">
                  <div className="flex items-center gap-1.5 font-semibold text-emerald-800">
                    <ShieldCheck className="h-4 w-4" />
                    <span>Sandbox Verification Passed</span>
                  </div>
                  <p>{verification.output}</p>
                  {branchName ? (
                    <p className="medha-mono font-medium text-emerald-950">
                      Committed to branch: <span className="underline">{branchName}</span>
                    </p>
                  ) : null}
                  {verification.verification_evidence.length > 0 ? (
                    <ul className="mt-1 list-disc pl-4 space-y-0.5 text-[11px] text-emerald-800">
                      {verification.verification_evidence.map((ev, i) => (
                        <li key={i}>{ev}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : null}

              {/* Delivery Outcome */}
              {delivering ? (
                <div className="flex items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 p-3 text-xs text-sky-800">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>Processing patch delivery…</span>
                </div>
              ) : deliverError ? (
                <div className="rounded-lg border border-medha-danger/30 bg-medha-danger-soft p-3 text-xs text-medha-danger space-y-2">
                  <div>
                    <p className="font-semibold">Delivery Failed</p>
                    <p className="mt-1">{deliverError}</p>
                  </div>
                  <Button
                    variant="secondary"
                    onClick={handleDeliver}
                    loading={delivering}
                    className="inline-flex items-center gap-1.5 text-xs text-medha-danger border-medha-danger/40 hover:bg-rose-100"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    <span>Retry Delivery</span>
                  </Button>
                </div>
              ) : delivery ? (
                <div className="rounded-lg border border-emerald-300 bg-emerald-50 p-3.5 text-xs text-emerald-950 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-emerald-900">{delivery.message}</span>
                    <Badge tone={delivery.delivery_method === "github_pr" ? "success" : "info"}>
                      {delivery.delivery_method === "github_pr" ? "GitHub PR" : "Local Git Branch"}
                    </Badge>
                  </div>

                  {delivery.delivery_method === "github_pr" && delivery.pr_url ? (
                    <a
                      href={delivery.pr_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 text-sm font-semibold text-emerald-800 underline hover:text-emerald-950 pt-1"
                    >
                      <GitPullRequest className="h-4 w-4" />
                      <span>View Pull Request #{delivery.pr_number} on GitHub</span>
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : null}

                  {delivery.delivery_method === "local_branch" && delivery.branch_name ? (
                    <div className="rounded border border-emerald-200 bg-emerald-100/70 p-2.5 text-emerald-900 space-y-1">
                      <p className="text-[11px] font-medium text-emerald-900">
                        Changes are committed to a local branch in this workspace (safe beta mode):
                      </p>
                      <div className="flex items-center justify-between rounded bg-white/80 px-2 py-1 font-mono text-xs text-slate-800 border border-emerald-200">
                        <code>git checkout {delivery.branch_name}</code>
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        {/* Footer controls */}
        <div className="flex items-center justify-between border-t border-medha-border bg-medha-surface-muted px-4 py-3">
          <Button variant="secondary" onClick={onClose}>
            {delivery?.delivered ? "Done" : "Cancel"}
          </Button>

          <div className="flex items-center gap-2">
            {plan?.can_auto_fix && !verification?.verified ? (
              <Button
                variant="primary"
                onClick={handleVerify}
                loading={verifying}
                disabled={loadingPlan || verifying || Boolean(planError)}
              >
                <span>Validate & Test in Sandbox</span>
                <ArrowRight className="h-4 w-4" />
              </Button>
            ) : verification?.verified && !delivery?.delivered ? (
              <Button
                variant="primary"
                onClick={handleDeliver}
                loading={delivering}
                disabled={delivering}
              >
                <GitPullRequest className="h-4 w-4" />
                <span>Approve & Create Pull Request</span>
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

