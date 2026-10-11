"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, FlaskConical, Loader2, Play } from "lucide-react";
import {
  ApiError,
  createDeployment,
  fetchDeployment,
  subscribeDeploymentEvents,
  type BackendSystemEvent,
  type DeploymentApiSnapshot,
} from "@/lib/api/client";
import { Badge, Button, EmptyState, ErrorBox, PageHeader, Panel } from "@/components/ui/primitives";
import { cn } from "@/lib/ui/cn";

const FALLBACK_SCENARIOS = [
  { id: "SUCCESSFUL_DEPLOYMENT", name: "Successful deployment", description: "Clean run: constraints agree, verification passes." },
  { id: "PORT_CONFLICT", name: "Port conflict", description: "Docker and Nginx claim the same port; CNP negotiates." },
  { id: "SECURITY_CONFLICT", name: "Security conflict", description: "Security policy collides with a publish plan." },
  { id: "VERIFICATION_FAILURE", name: "Verification failure", description: "A gate fails and bounded replanning kicks in." },
  { id: "PARTIAL_FAILURE", name: "Partial failure", description: "One service fails; scoped rollback preserves the rest." },
];

interface ScenarioInfo {
  id: string;
  name: string;
  description: string;
}

type Phase = "idle" | "starting" | "running" | "done" | "error";

export default function DemoPage() {
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>(FALLBACK_SCENARIOS);
  const [scenario, setScenario] = useState("PORT_CONFLICT");
  const [repoUrl, setRepoUrl] = useState("https://github.com/example/medha-sample-app");
  const [port, setPort] = useState("8080");
  const [phase, setPhase] = useState<Phase>("idle");
  const [problem, setProblem] = useState<string | null>(null);
  const [deploymentId, setDeploymentId] = useState<string | null>(null);
  const [events, setEvents] = useState<BackendSystemEvent[]>([]);
  const [snapshot, setSnapshot] = useState<DeploymentApiSnapshot | null>(null);
  const subRef = useRef<{ close: () => void } | null>(null);
  const seenRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/demo/scenarios", { cache: "no-store" });
        if (!res.ok) return;
        const body = (await res.json()) as {
          scenarios?: { id?: string; name?: string; description?: string }[];
        };
        if (!cancelled && Array.isArray(body.scenarios) && body.scenarios.length > 0) {
          setScenarios(
            body.scenarios.map((s, i) => ({
              id: s.id ?? FALLBACK_SCENARIOS[i]?.id ?? `scenario-${i}`,
              name: s.name ?? s.id ?? `Scenario ${i + 1}`,
              description: s.description ?? "",
            })),
          );
        }
      } catch {
        /* offline — static fallback list stays */
      }
    })();
    return () => {
      cancelled = true;
      subRef.current?.close();
    };
  }, []);

  const start = useCallback(async () => {
    subRef.current?.close();
    seenRef.current = new Set();
    setEvents([]);
    setSnapshot(null);
    setProblem(null);
    const portNum = Number.parseInt(port, 10);
    if (!Number.isFinite(portNum)) {
      setProblem("Target port must be a number.");
      return;
    }
    setPhase("starting");
    try {
      const created = await createDeployment({
        repository_url: repoUrl.trim() || "https://github.com/example/medha-sample-app",
        mode: "demo",
        scenario: scenario as "PORT_CONFLICT",
        target: { host: "localhost", port: portNum },
        intent: "Guest demo run (simulated)",
      });
      setDeploymentId(created.deployment_id);
      setPhase("running");
      const sub = subscribeDeploymentEvents(created.deployment_id, {
        onEvent: (event) => {
          if (seenRef.current.has(event.event_id)) return;
          seenRef.current.add(event.event_id);
          setEvents((prev) => [...prev.slice(-199), event]);
        },
        onTerminal: () => {
          setPhase("done");
          void fetchDeployment(created.deployment_id)
            .then(setSnapshot)
            .catch(() => undefined);
        },
        onError: (message) => {
          setProblem(`${message} The demo engine may still be running — open the run detail to check.`);
          void fetchDeployment(created.deployment_id)
            .then((api) => {
              setSnapshot(api);
              if (["completed", "failed", "partial_recovery", "cancelled", "awaiting_approval"].includes(api.status)) {
                setPhase("done");
              }
            })
            .catch(() => undefined);
        },
      });
      subRef.current = sub;
    } catch (err) {
      setPhase("error");
      setProblem(
        err instanceof ApiError
          ? err.message
          : "Cannot reach MEDHA backend. Is the API service running?",
      );
    }
  }, [port, repoUrl, scenario]);

  const activeScenario = scenarios.find((s) => s.id === scenario) ?? null;

  return (
    <div className="min-h-screen bg-medha-bg">
      <header className="border-b border-medha-border bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3 sm:px-6">
          <Link href="/" className="text-[17px] font-bold tracking-tight text-medha-text">
            MEDHA
          </Link>
          <Badge tone="neutral">DEMO · SIMULATED</Badge>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-5 px-4 py-6 sm:px-6">
        <PageHeader
          title="Guest demo"
          subtitle="No registration needed. This runs the deterministic demo engine — simulated fixtures, explicitly labeled, with zero changes to real infrastructure."
          breadcrumbs={
            <Link href="/" className="inline-flex items-center gap-1 text-sm text-medha-secondary hover:text-medha-text">
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Back to landing
            </Link>
          }
          actions={
            <Link
              href="/sign-in"
              className="rounded-lg border border-medha-border bg-white px-4 py-2 text-sm font-semibold text-medha-text hover:bg-medha-muted/60"
            >
              Sign in for durable projects
            </Link>
          }
        />

        <Panel
          title="Run a simulated deployment"
          eyebrow="Demo setup"
          description="Pick a failure scenario the demo engine will simulate. Repository URL is fixture metadata only — nothing is cloned or deployed."
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="demo-scenario" className="medha-label">Scenario</label>
              <select
                id="demo-scenario"
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
                className="field-input mt-1"
              >
                {scenarios.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
              {activeScenario?.description ? (
                <p className="mt-1 text-[12px] text-medha-tertiary">{activeScenario.description}</p>
              ) : null}
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label htmlFor="demo-port" className="medha-label">Target port</label>
                <input id="demo-port" className="field-input mt-1" value={port} onChange={(e) => setPort(e.target.value)} inputMode="numeric" />
              </div>
              <div>
                <span className="medha-label">Engine</span>
                <p className="mt-2 rounded-lg border border-medha-border bg-medha-muted px-3 py-2 text-sm font-medium text-medha-secondary">
                  demo
                </p>
              </div>
            </div>
          </div>
          <div className="mt-3">
            <label htmlFor="demo-repo" className="medha-label">Repository URL (fixture label only)</label>
            <input id="demo-repo" className="field-input mt-1" value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} placeholder="https://github.com/example/app" />
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button variant="primary" onClick={() => void start()} loading={phase === "starting" || phase === "running"}>
              <Play className="h-4 w-4" aria-hidden />
              {phase === "running" ? "Demo running…" : "Start simulated run"}
            </Button>
            {deploymentId ? (
              <Link href={`/runs/${deploymentId}`} className="inline-flex items-center gap-1 text-sm font-semibold text-medha-accent hover:underline">
                Open full run detail →
              </Link>
            ) : null}
          </div>
          {problem ? (
            <div className="mt-3">
              <ErrorBox message={problem} onRetry={() => void start()} />
            </div>
          ) : null}
        </Panel>

        {phase === "idle" ? (
          <EmptyState
            title="No demo run yet"
            body="Start a simulated run above. Live system events, the negotiated outcome, and the verdict will appear here — every line labeled DEMO/MOCK."
          />
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Panel
              title="Live system trace"
              eyebrow={`DEMO/MOCK · ${events.length} events`}
              description={deploymentId ? `deployment_id=${deploymentId}` : undefined}
            >
              {events.length === 0 ? (
                <p className="flex items-center gap-2 text-sm text-medha-secondary">
                  <Loader2 className="h-4 w-4 animate-spin text-medha-run" aria-hidden />
                  Waiting for the first backend event…
                </p>
              ) : (
                <ol className="max-h-96 space-y-1.5 overflow-y-auto" aria-live="polite">
                  {events.map((e) => (
                    <li key={e.event_id} className="flex items-start gap-2 rounded-lg border border-medha-border bg-white px-2.5 py-1.5 text-[12px]">
                      <span
                        className={cn(
                          "status-dot mt-1",
                          e.level === "error" ? "bg-medha-danger"
                          : e.level === "warning" ? "bg-medha-warning"
                          : "bg-medha-run",
                        )}
                        aria-hidden
                      />
                      <div className="min-w-0">
                        <p className="font-medium text-medha-text">
                          {e.type}
                          <span className="ml-1.5 font-normal text-medha-tertiary">{e.stage ?? "system"}</span>
                        </p>
                        <p className="truncate text-medha-secondary">{e.message}</p>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </Panel>

            <Panel
              title="Demo verdict"
              eyebrow="DEMO/MOCK result"
              description="Simulated outcome — not evidence of real infrastructure execution."
            >
              {!snapshot ? (
                <p className="flex items-center gap-2 text-sm text-medha-secondary">
                  <FlaskConical className="h-4 w-4" aria-hidden />
                  {phase === "done" ? "Loading result…" : "Verdict appears when the simulated run finishes."}
                </p>
              ) : (
                <dl className="space-y-2 text-sm">
                  <div className="flex gap-2">
                    <dt className="w-24 shrink-0 text-medha-tertiary">Status</dt>
                    <dd className="font-semibold text-medha-text">{snapshot.status}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-24 shrink-0 text-medha-tertiary">Scenario</dt>
                    <dd className="text-medha-text">{snapshot.scenario ?? "—"}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-24 shrink-0 text-medha-tertiary">Stage</dt>
                    <dd className="text-medha-text">{snapshot.current_stage ?? "—"}</dd>
                  </div>
                  {snapshot.error_summary ? (
                    <div className="flex gap-2">
                      <dt className="w-24 shrink-0 text-medha-tertiary">Summary</dt>
                      <dd className="text-medha-text">{snapshot.error_summary}</dd>
                    </div>
                  ) : null}
                  <p className="rounded-lg border border-medha-border bg-medha-muted px-3 py-2 text-[12px] text-medha-secondary">
                    DEMO/MOCK — simulated by the offline demo engine. Sign in to run the real
                    pipeline against your local host.
                  </p>
                </dl>
              )}
            </Panel>
          </div>
        )}
      </main>
    </div>
  );
}
