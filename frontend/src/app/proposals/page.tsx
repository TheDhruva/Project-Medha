"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/AppShell";
import {
  decideProposal,
  fetchProposals,
  type Proposal,
} from "@/lib/api/client";

function statusTone(status: string): string {
  switch (status) {
    case "ready":
      return "border-medha-run/25 bg-medha-run-soft text-medha-run-ink";
    case "approved":
    case "executing":
      return "border-medha-success/30 bg-medha-success-soft text-medha-success";
    case "executed":
      return "border-medha-success/30 bg-medha-success-soft text-medha-success";
    case "rejected":
    case "stale":
    case "failed":
      return "border-medha-danger/30 bg-medha-danger-soft text-medha-danger";
    case "superseded":
      return "border-medha-border bg-medha-muted text-medha-secondary";
    default:
      return "border-medha-border bg-medha-muted text-medha-secondary";
  }
}

export default function ProposalsPage() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [error, setError] = useState<string>("");
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(() => {
    void fetchProposals({ limit: 100 }).then(
      (body) => {
        setProposals(body.proposals);
        setError("");
      },
      (err: Error) => setError(err.message || "Could not load proposals."),
    );
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function decide(proposalId: string, decision: "approve" | "reject") {
    setBusy(proposalId + decision);
    setError("");
    try {
      await decideProposal(proposalId, decision);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <AppShell>
      <div className="space-y-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-medha-text">
            Approval proposals
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-medha-secondary">
            Push-triggered plans waiting for a human decision. Nothing executes
            before approval; approving revalidates the exact plan hash first.
          </p>
        </div>

        {error ? (
          <p role="alert" className="text-sm text-medha-danger">{error}</p>
        ) : null}

        {proposals.length === 0 ? (
          <p className="text-sm text-medha-secondary">
            No proposals yet. Configure the GitHub webhook to receive push-triggered plans.
          </p>
        ) : (
          <ul className="space-y-3">
            {proposals.map((proposal) => (
              <li
                key={proposal.proposal_id}
                className="medha-panel animate-medha-in p-4"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-medha-text">
                      {proposal.repository} · {proposal.branch}
                    </p>
                    <p className="medha-mono mt-0.5 text-[13px] text-medha-tertiary">
                      {proposal.target_sha.slice(0, 12)} · {proposal.proposal_id}
                    </p>
                  </div>
                  <span
                    className={`inline-flex shrink-0 items-center rounded-full border px-2.5 py-1 text-[12px] font-semibold ${statusTone(proposal.status)}`}
                  >
                    {proposal.status}
                  </span>
                </div>
                {proposal.status === "ready" ? (
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      disabled={busy != null}
                      onClick={() => void decide(proposal.proposal_id, "approve")}
                      className="rounded-medha-sm bg-medha-text px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
                    >
                      {busy === proposal.proposal_id + "approve" ? "Approving…" : "Approve & execute"}
                    </button>
                    <button
                      type="button"
                      disabled={busy != null}
                      onClick={() => void decide(proposal.proposal_id, "reject")}
                      className="rounded-medha-sm border border-medha-border bg-white px-3 py-2 text-sm font-medium text-medha-secondary hover:text-medha-text disabled:opacity-50"
                    >
                      {busy === proposal.proposal_id + "reject" ? "Rejecting…" : "Reject"}
                    </button>
                    {proposal.deployment_id ? (
                      <Link
                        href={`/runs/${encodeURIComponent(proposal.deployment_id)}`}
                        className="rounded-medha-sm px-3 py-2 text-sm font-medium text-medha-accent hover:underline"
                      >
                        View analysis →
                      </Link>
                    ) : null}
                  </div>
                ) : null}
                {proposal.decided_by ? (
                  <p className="mt-2 text-[13px] text-medha-tertiary">
                    Decided by {proposal.decided_by}
                    {proposal.decided_at ? ` · ${proposal.decided_at}` : ""}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </AppShell>
  );
}
