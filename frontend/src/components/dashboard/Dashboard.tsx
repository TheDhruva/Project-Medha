"use client";

import { useEffect, useMemo, useState } from "react";
import { CausalExecutionGraph } from "@/components/graph/CausalExecutionGraph";
import { VerificationPanel } from "@/components/verification/VerificationPanel";
import { ConstraintNegotiation } from "@/components/constraints/ConstraintNegotiation";
import { Badge } from "@/components/ui/primitives";
import { EnvBadge } from "@/components/ui/Section";
import { useDeployment, useOptionalDeployment } from "@/context/DeploymentContext";
import { cn } from "@/lib/ui/cn";
import {
  ATLAS_CONTRIBUTORS,
  ATLAS_LATEST_PUSH,
  ATLAS_DEPLOYMENTS,
  ATLAS_CEG_NODES,
  ATLAS_CEG_EDGES,
  ATLAS_NEGOTIATION,
  ATLAS_VERIFICATION_CHECKS,
  ATLAS_ALERTS,
  ATLAS_SERVICE_HEALTH,
  ATLAS_DEPLOYMENT_TREND,
  ATLAS_REPLAN_ATTEMPT,
  ATLAS_RECENT_ACTIVITY,
} from "@/lib/demo/atlas-fixtures";

function useAtlasDemoSnapshot() {
  const deployment = useOptionalDeployment();
  const isDeploying = deployment?.form?.mode === "demo";
  const repositoryUrl = deployment?.form?.repositoryUrl || "https://github.com/atlas-labs/atlas-commerce";
  const branch = deployment?.form?.baseRevision ? "main" : "unknown";

  const [runId, setRunId] = useState<string | null>(null);
  const [scenario, setScenario] = useState<string | null>("PORT_CONFLICT");

  useEffect(() => {
    if (isDeploying && !runId) {
      setRunId("dep_atlas_005");
      setScenario("PORT_CONFLICT");
    }
  }, [isDeploying, runId]);

  return { runId, scenario, isDeploying };
}

function useDashboardData() {
  const { runId, scenario, isDeploying } = useAtlasDemoSnapshot();
  const deployment = useOptionalDeployment();

  if (deployment && deployment.snapshot) {
    const snap = deployment.snapshot;
    const status = snap.runStatus ?? "running";
    const mode = deployment.form?.mode ?? "real";

    const checks = snap.verification?.checks ?? [];
    const passed = checks.filter((c: any) => c.status === "pass").length;
    const total = checks.length;
    const successRate = total > 0 ? Math.round((passed / total) * 100) : null;
    const negotiation = snap.negotiation;
    const constraints = negotiation ? negotiation.round : 0;

    const latestPush = {
      commitHash: snap.explain?.technicalText?.slice(30) || "a82f31c",
      shortHash: (snap.explain?.technicalText ?? "a82f31c").substring(0, 7),
      author: "Priya S.",
      title: "Optimize checkout queries",
      summary: "Adds query batching and an index for order lookups.",
      changedFiles: 3,
      additions: 124,
      deletions: 38,
      relativeTimestamp: "18 min ago",
    };

    const serviceHealth = [
      { service: "web frontend", status: "healthy" },
      { service: "API service", status: "healthy" },
      { service: "background worker", status: "degraded" },
      { service: "PostgreSQL", status: "healthy" },
      { service: "Redis", status: "elevated_retries" },
    ];

    const alerts = snap.agents?.length
      ? []
      : [
          {
            id: "alert_redis",
            severity: "high",
            title: "Redis connection failures",
            description: "Elevated retry rates detected on the background worker.",
            affectedService: "background worker",
            timestamp: "2026-10-10T11:14:00Z",
            investigationPath: "Check Redis connectivity, review connection pool settings, verify worker heartbeat",
          },
          {
            id: "alert_vulnerability",
            severity: "medium",
            title: "Dependency vulnerability requiring review",
            description: "PostgreSQL driver version 2.3.5 has a known CVE.",
            affectedService: "API service",
            investigationPath: "Run dependency audit, update postgres driver, verify compatibility",
          },
          {
            id: "alert_drift",
            severity: "medium",
            title: "Deployment configuration drift",
            description: "Nginx configuration has drifted from the canonical spec.",
            affectedService: "nginx",
            investigationPath: "Apply configuration drift remediation, redeploy nginx",
          },
        ];

    const deploymentTrend = [
      { date: "2026-09-12", success: true },
      { date: "2026-09-13", success: true },
      { date: "2026-09-14", success: false },
      { date: "2026-09-15", success: true },
      { date: "2026-09-16", success: true },
      { date: "2026-09-17", success: true },
      { date: "2026-09-18", success: true },
      { date: "2026-09-19", success: true },
      { date: "2026-09-20", success: true },
      { date: "2026-09-21", success: true },
      { date: "2026-09-22", success: true },
      { date: "2026-09-23", success: true },
      { date: "2026-09-24", success: true },
      { date: "2026-09-25", success: true },
      { date: "2026-09-26", success: true },
      { date: "2026-09-27", success: true },
      { date: "2026-09-28", success: true },
      { date: "2026-09-29", success: true },
      { date: "2026-09-30", success: true },
      { date: "2026-10-01", success: true },
      { date: "2026-10-02", success: true },
      { date: "2026-10-03", success: true },
      { date: "2026-10-04", success: false },
      { date: "2026-10-05", success: true },
      { date: "2026-10-06", success: true },
      { date: "2026-10-07", success: true },
      { date: "2026-10-08", success: true },
      { date: "2026-10-09", success: true },
      { date: "2026-10-10", success: false },
      { date: "2026-10-11", success: true },
      { date: "2026-10-12", success: true },
    ];

    const contributors = [
      { initials: "PS", name: "Priya S.", role: "API", commits: 12 },
      { initials: "RK", name: "Rahul K.", role: "Infrastructure", commits: 9 },
      { initials: "MT", name: "Maya T.", role: "Frontend", commits: 8 },
    ];

    return {
      status,
      successRate,
      negotiation,
      latestPush,
      serviceHealth,
      alerts,
      deploymentTrend,
      contributors,
    };
  }

  // Fallback: use Atlas Commerce deterministic fixtures
  return {
    status: isDeploying ? "running" : "succeeded",
    successRate: 87,
    negotiation: ATLAS_NEGOTIATION,
    latestPush: ATLAS_LATEST_PUSH,
    serviceHealth: ATLAS_SERVICE_HEALTH,
    alerts: ATLAS_ALERTS,
    deploymentTrend: ATLAS_DEPLOYMENT_TREND,
    contributors: ATLAS_CONTRIBUTORS.map((c) => ({
      initials: c.initials,
      name: c.name,
      role: c.role,
      commits: c.commits,
    })),
  };
}

function MetricTile({ label, value, tone = "neutral", subtitle }: { label: string; value: string | number; tone?: "success" | "warning" | "error" | "neutral"; subtitle?: string }) {
  const toneCls =
    tone === "success"
      ? "rounded-md border border-medha-success/30 bg-medha-success-soft text-medha-success"
      : tone === "warning"
        ? "rounded-md border border-medha-warning/30 bg-medha-warning-soft text-medha-warning"
        : tone === "error"
          ? "rounded-md border border-medha-danger/30 bg-medha-danger-soft text-medha-danger"
          : "rounded-md border border-medha-border bg-medha-surface text-medha-secondary";

  return (
    <div className={cn("h-24 flex flex-col items-center justify-center", toneCls)}>
      <p className="medha-label text-xs uppercase tracking-wider text-medha-secondary">{label}</p>
      <p className="mt-2 font-semibold text-medha-text">{value}</p>
      {subtitle && <p className="mt-1 text-[10px] text-medha-secondary">{subtitle}</p>}
    </div>
  );
}

function LatestPushCard({ push }: { push: any }) {
  return (
    <div className="rounded-md border border-medha-border bg-medha-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="medha-label text-xs uppercase tracking-wider text-medha-secondary">Latest commit</p>
          <p className="mt-1 font-medium text-medha-text">{push.title}</p>
          <p className="mt-0.5 text-[10px] text-medha-secondary">
            {push.authorInitials} · {push.relativeTimestamp}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <p className="medha-mono text-[10px] text-medha-tertiary">{push.shortHash}</p>
          <p className="text-[9px] text-medha-secondary">{push.summary}</p>
        </div>
      </div>
      <p className="mt-3 text-[10px] text-medha-secondary">
        {push.changedFiles} files changed · {push.additions} additions · {push.deletions} deletions
      </p>
    </div>
  );
}

function ContributorsPanel({ contributors }: { contributors: any[] }) {
  return (
    <div className="rounded-md border border-medha-border bg-medha-surface p-4">
      <p className="medha-label text-xs uppercase tracking-wider text-medha-secondary">Contributors</p>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
        {contributors.map((c) => (
          <div key={c.initials} className="flex items-center gap-2">
            <span className="rounded-lg bg-medha-accent-soft p-1.5 text-medha-accent-ink text-xs font-medium">{c.initials}</span>
            <div>
              <p className="medha-mono text-[10px] text-medha-text">{c.name}</p>
              <p className="text-[9px] text-medha-secondary">{c.role} · {c.commits} commits</p>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 text-[9px] text-medha-secondary cursor-pointer" onClick={() => window.alert("Full contributor list available")}>
        View all contributors
      </div>
    </div>
  );
}

function ServiceHealthPanel({ serviceHealth }: { serviceHealth: any[] }) {
  return (
    <div className="rounded-md border border-medha-border bg-medha-surface p-4">
      <p className="medha-label text-xs uppercase tracking-wider text-medha-secondary">Service health</p>
      <div className="mt-3 grid grid-cols-5 gap-2">
        {serviceHealth.map((s) => {
          const statusMap: Record<string, "success" | "warning" | "error" | "neutral"> = {
            healthy: "success",
            degraded: "warning",
            elevated_retries: "warning",
            failed: "error",
            unknown: "neutral",
          };
          const tone = statusMap[s.status] ?? "neutral";
          const badgeCls =
            tone === "success"
              ? "rounded py-1.5 px-2 text-[9px] font-semibold border-medha-success/30 bg-medha-success-soft text-medha-success"
              : tone === "warning"
                ? "rounded py-1.5 px-2 text-[9px] font-semibold border-medha-warning/30 bg-medha-warning-soft text-medha-warning"
                : tone === "error"
                  ? "rounded py-1.5 px-2 text-[9px] font-semibold border border-medha-danger/30 bg-medha-danger-soft text-medha-danger"
                  : "rounded py-1.5 px-2 text-[9px] font-semibold border-medha-border bg-medha-surface text-medha-secondary";

          return (
            <div
              key={s.service}
              className={cn("flex items-center gap-2 rounded py-1.5 px-2 text-[9px] font-semibold", badgeCls)}
            >
              <span className={cn("status-dot", tone === "success" ? "bg-medha-success" : tone === "warning" ? "bg-medha-warning" : tone === "error" ? "bg-medha-danger" : "bg-medha-tertiary")} aria-hidden />
              <span>{s.service}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ActiveAlertsPanel({ alerts }: { alerts: any[] }) {
  return (
    <div className="rounded-md border border-medha-border bg-medha-surface p-4">
      <p className="medha-label text-xs uppercase tracking-wider text-medha-secondary">Active alerts</p>
      <div className="mt-3 space-y-3 max-h-80 overflow-y-auto">
        {alerts.map((a) => {
          const severityCls =
            a.severity === "high"
              ? "rounded px-3 py-2 border border-medha-danger/30 bg-medha-danger-soft text-medha-danger"
              : a.severity === "medium"
                ? "rounded px-3 py-2 border border-medha-warning/30 bg-medha-warning-soft text-medha-warning"
                : "rounded px-3 py-2 border border-medha-border bg-medha-surface text-medha-secondary";

          return (
            <div
              key={a.id}
              className={cn("flex items-start gap-2 rounded px-3 py-2", severityCls)}
            >
              <span
                className={cn("status-dot", a.severity === "high" ? "bg-medha-danger" : a.severity === "medium" ? "bg-medha-warning" : "bg-medha-tertiary")}
                aria-hidden
              />
              <div className="flex-1 min-w-0">
                <p className="medha-mono text-[10px] font-medium text-medha-text truncate">{a.title}</p>
                <p className="text-[9px] text-medha-secondary truncate">{a.description}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DeploymentHistoryChart({ trend }: { trend: any[] }) {
  const dayLabels = trend.map((t) => t.date.slice(-2));

  return (
    <div className="rounded-md border border-medha-border bg-medha-surface p-4">
      <p className="medha-label text-xs uppercase tracking-wider text-medha-secondary">Deployment success rate (30 days)</p>
      <div className="mt-3 grid grid-cols-30 gap-0.5 h-16">
        {trend.map((t, i) => {
          const isSuccess = t.success;
          const height = isSuccess ? "8" : "3";
          const bgClass = isSuccess
            ? "bg-medha-success/40"
            : "bg-medha-danger/30";
          return (
            <div
              key={i}
              className={cn(
                "flex flex-col items-center justify-center rounded-t medha-mono text-[8px] text-medha-secondary",
                bgClass,
                isSuccess ? "border-t border-medha-success" : "border-t border-medha-danger",
              )}
            >
              {dayLabels[i]}
              <span className="self-end text-[9px] text-medha-success">{isSuccess ? "✓" : "✗"}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function RecentActivityList({ activities }: { activities: any[] }) {
  return (
    <div className="rounded-md border border-medha-border bg-medha-surface p-4">
      <p className="medha-label text-xs uppercase tracking-wider text-medha-secondary">Recent activity</p>
      <div className="mt-3 space-y-2 max-h-100 overflow-y-auto">
        {activities.map((a) => {
          const time = a.timestamp ? new Date(a.timestamp).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "—";
          const typeIcon = a.type === "push" ? "GitPullRequest" : a.type === "deployment" ? "Rocket" : a.type === "negotiation" ? "Swords" : a.type === "verification" ? "ShieldCheck" : "Info";

          return (
            <div key={a.timestamp} className="flex items-center gap-3 px-2 py-1 hover:bg-medha-surface-muted/30 cursor-pointer">
              <span className="medha-mono text-[9px] text-medha-secondary">{time}</span>
              <span className="text-medha-text truncate">{a.title}</span>
              <span className="text-[9px] text-medha-secondary">{a.description || ""}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function Dashboard() {
  const { snapshot } = useDeployment();
  const deployment = useOptionalDeployment();
  const isDeploying = deployment?.form?.mode === "demo";
  const repositoryUrl = deployment?.form?.repositoryUrl || "https://github.com/atlas-labs/atlas-commerce";
  const branch = deployment?.form?.baseRevision || "main";
  const data = useDashboardData();

  const status = data.status;
  const successRate = data.successRate;
  const negotiation = data.negotiation ?? { round: 0, maxRounds: 0, status: "idle" };
  const latestPush = data.latestPush;
  const serviceHealth = data.serviceHealth;
  const alerts = data.alerts;
  const deploymentTrend = data.deploymentTrend;
  const contributors = data.contributors;

  const checkStatuses = snapshot?.verification?.checks ?? [];
  const passedChecks = checkStatuses.filter((c: any) => c.status === "pass").length;
  const totalChecks = checkStatuses.length;
  const deploymentSuccessRate = totalChecks > 0 ? Math.round((passedChecks / totalChecks) * 100) : successRate ?? 0;
  const serviceHealthCount = serviceHealth.filter((s: any) => s.status === "healthy").length;
  const serviceHealthTotal = serviceHealth.length;

  return (
    <section className="min-h-screen bg-medha-bg">
      <div className="flex flex-col lg:flex-row">
        {/* A. Project header — full width on mobile, compact on desktop */}
        <div className="w-full lg:w-auto lg:static lg:block lg:h-fit">
          <div className="border-b border-medha-border bg-medha-surface p-4 sm:p-6">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
                  {isDeploying ? "Atlas Commerce" : "My Project"}
                </h2>
                <p className="mt-1 text-sm text-medha-secondary">
                  {isDeploying
                    ? "atlas-labs/atlas-commerce · main (DEMO mode)"
                    : `Repository on ${repositoryUrl || "unknown"} · ${branch || "main"}`}
                </p>
              </div>

              <div className="flex items-center gap-2">
                {isDeploying ? (
                  <Badge tone="neutral">DEMO · SIMULATED</Badge>
                ) : (
                  <Badge tone="info">LIVE · LOCAL</Badge>
                )}

                {/* Primary New run action — only in demo mode when no run is actively open */}
                {isDeploying && (
                  <button
                    type="button"
                    onClick={() => window.location.pathname = "/runs/new"}
                    className="rounded-md px-3 py-1.5 text-[10px] font-medium text-medha-accent hover:bg-medha-accent-soft text-medha-accent-ink transition-colors"
                    title="Start new DEMO run"
                  >
                    New run
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Compact summary metrics */}
          <div className="grid grid-cols-2 gap-3 mt-4">
            <MetricTile
              label="Deployment success rate"
              value={`${deploymentSuccessRate}%`}
              tone={deploymentSuccessRate >= 80 ? "success" : deploymentSuccessRate >= 50 ? "warning" : "error"}
              subtitle="Last 30 days"
            />
            <MetricTile
              label="Negotiation activity"
              value={`${negotiation.round} / ${negotiation.maxRounds}`}
              tone={negotiation.status === "resolved" ? "success" : "warning"}
              subtitle="CNPs completed"
            />
            <MetricTile
              label="Verification status"
              value={status === "succeeded" || status === "partial_recovery" ? "passed" : "failed"}
              tone={status === "succeeded" || status === "partial_recovery" ? "success" : "error"}
              subtitle="Checks passed"
            />
            <MetricTile
              label="Service health"
              value={`${serviceHealthCount}/${serviceHealthTotal}`}
              tone="success"
              subtitle="of 5 services healthy"
            />
          </div>
        </div>

        {/* Main analytical row */}
        <div className="lg:w-[calc(100%-64px)] lg:overflow-x-hidden lg:pt-6">
          <div className="grid grid-cols-1 lg:grid-cols-[700px_300px] gap-6">
            {/* B. Causal Execution Graph — occupies ~55-60% of central analytical row */}
            <div className="lg:col-span-1 lg:row-span-1">
              <CausalExecutionGraph />
            </div>

            {/* C. Constraint Negotiation panel — beside CEG */}
            <div className="lg:col-span-1 lg:row-span-1">
              <ConstraintNegotiation />
            </div>

            {/* D. Verification and replanning — below the analytical row */}
            <div className="mt-4 lg:mt-0 grid grid-cols-1 lg:row-span-2 gap-4">
              <VerificationPanel />
            </div>

            {/* E. Deployment history — compact chart */}
            <div className="mt-4 lg:mt-0 grid grid-cols-1 gap-4">
              <DeploymentHistoryChart trend={deploymentTrend} />
            </div>

            {/* F. Latest push card */}
            <div className="mt-4 lg:mt-0 grid grid-cols-1 gap-4">
              <LatestPushCard push={latestPush} />
            </div>

            {/* G. Contributors — compact panel */}
            <div className="mt-4 lg:mt-0 grid grid-cols-1 gap-4">
              <ContributorsPanel contributors={contributors} />
            </div>

            {/* H. Service health panel */}
            <div className="mt-4 lg:mt-0 grid grid-cols-1 gap-4">
              <ServiceHealthPanel serviceHealth={serviceHealth} />
            </div>

            {/* I. Active alerts */}
            <div className="mt-4 lg:mt-0">
              <ActiveAlertsPanel alerts={alerts} />
            </div>

            {/* J. Recent activity */}
            <div className="mt-4 lg:mt-0 grid grid-cols-1 gap-4">
              <RecentActivityList activities={ATLAS_RECENT_ACTIVITY} />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}