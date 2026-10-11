"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ApiError,
  createDeployment,
  eventsUrl,
  fetchDeployment,
  fetchRunHydration,
  type BackendSystemEvent,
} from "@/lib/api/client";
import {
  applyBackendEvent,
  buildBackendSnapshot,
  createRunningSnapshot,
  isTerminalDeploymentStatus,
  mapVerificationArtifact,
  reconcileTerminalState,
} from "@/lib/api/eventMapper";
import { createIdleSnapshot } from "@/lib/demo/frames";
import { SCENARIOS } from "@/lib/demo/scenarios";
import type {
  CriticView,
  DeployFormState,
  DeploymentSnapshot,
  ScenarioId,
  VerificationView,
  ViewMode,
} from "@/lib/demo/types";

interface DeploymentContextValue {
  form: DeployFormState;
  setForm: (patch: Partial<DeployFormState>) => void;
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  snapshot: DeploymentSnapshot;
  selectNode: (id: string | null) => void;
  startDeployment: () => void;
  viewDemo: () => void;
  reset: () => void;
  openDeployment: (deploymentId: string) => Promise<void>;
  isRunning: boolean;
  hydrating: boolean;
  scenarios: typeof SCENARIOS;
  connectionError: string | null;
}

const DeploymentContext = createContext<DeploymentContextValue | null>(null);

const DEFAULT_FORM: DeployFormState = {
  repositoryUrl: "https://github.com/example/medha-sample-app",
  targetHost: "localhost",
  targetPort: "8080",
  intent: "Deploy the application securely",
  scenario: "PORT_CONFLICT",
  mode: "demo",
  baseRevision: "",
  targetRevision: "",
};

export function DeploymentProvider({ children }: { children: ReactNode }) {
  const [form, setFormState] = useState<DeployFormState>(DEFAULT_FORM);
  const [viewMode, setViewMode] = useState<ViewMode>("simple");
  const [snapshot, setSnapshot] = useState<DeploymentSnapshot>(createIdleSnapshot);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [hydrating, setHydrating] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);
  const seenEventsRef = useRef<Set<string>>(new Set());

  const closeStream = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
  }, []);

  useEffect(() => () => closeStream(), [closeStream]);

  const setForm = useCallback((patch: Partial<DeployFormState>) => {
    setFormState((prev) => ({ ...prev, ...patch }));
  }, []);

  const selectNode = useCallback((id: string | null) => {
    setSnapshot((prev) => ({ ...prev, selectedNodeId: id }));
  }, []);

  const reset = useCallback(() => {
    closeStream();
    seenEventsRef.current = new Set();
    setConnectionError(null);
    setSnapshot(createIdleSnapshot());
  }, [closeStream]);

  const subscribe = useCallback(
    (deploymentId: string) => {
      closeStream();
      seenEventsRef.current = new Set();
      const source = new EventSource(eventsUrl(deploymentId));
      sourceRef.current = source;

      source.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as BackendSystemEvent;
          if (seenEventsRef.current.has(event.event_id)) return;
          seenEventsRef.current.add(event.event_id);
          setSnapshot((prev) => applyBackendEvent(prev, event));
          if (
            event.type === "deployment.completed" ||
            event.type === "deployment.failed"
          ) {
            closeStream();
          }
        } catch {
          setConnectionError("Failed to parse backend event.");
        }
      };

      source.onerror = () => {
        // EventSource retries automatically; surface a soft warning. If the
        // backend actually finished the deployment while the stream was down,
        // reconcile to the terminal state so the UI never stays "running".
        setConnectionError(
          "Lost connection to MEDHA backend event stream. Is the API running on :8000?",
        );
        fetchDeployment(deploymentId)
          .then((api) => {
            setSnapshot((prev) => reconcileTerminalState(prev, api));
            if (isTerminalDeploymentStatus(api.status)) closeStream();
          })
          .catch(() => {
            /* backend unreachable — EventSource keeps retrying */
          });
      };
    },
    [closeStream],
  );

  const startWithScenario = useCallback(
    async (scenario: ScenarioId | null) => {
      closeStream();
      setConnectionError(null);
      const mode = form.mode;
      setSnapshot({
        ...createIdleSnapshot(),
        scenario: mode === "demo" ? scenario : null,
        isDemo: mode === "demo",
        runStatus: "running",
        explain: {
          currentStage: null,
          round: null,
          statusLabel: "Starting",
          simpleText: "Contacting MEDHA backend…",
          technicalText: "POST /api/deploy · awaiting deployment_id",
        },
      });

      const port = Number.parseInt(form.targetPort, 10);
      if (!Number.isFinite(port)) {
        setConnectionError("Target port must be a number.");
        setSnapshot(createIdleSnapshot());
        return;
      }

      try {
        const response = await createDeployment({
          repository_url: form.repositoryUrl,
          mode,
          scenario: mode === "demo" ? scenario : null,
          target: { host: form.targetHost, port },
          intent: form.intent,
          // Revisions scope change-impact analysis for local git repos.
          // Sent only in real mode when both are provided; otherwise null
          // so the backend honestly skips change-intel instead of guessing.
          base_revision:
            mode === "real" && form.baseRevision.trim() ? form.baseRevision.trim() : null,
          target_revision:
            mode === "real" && form.targetRevision.trim()
              ? form.targetRevision.trim()
              : null,
        });
        setSnapshot(
          createRunningSnapshot(
            response.deployment_id,
            mode === "demo" ? (scenario as ScenarioId) : null,
            mode === "demo",
          ),
        );
        subscribe(response.deployment_id);
      } catch (error) {
        const message =
          error instanceof ApiError
            ? error.message
            : "Cannot reach MEDHA backend. Is the API service running?";
        setConnectionError(message);
        setSnapshot({
          ...createIdleSnapshot(),
          scenario: mode === "demo" ? scenario : null,
          isDemo: mode === "demo",
          runStatus: "failed",
          explain: {
            currentStage: null,
            round: null,
            statusLabel: "Backend unavailable",
            simpleText: message,
            technicalText: "POST /api/deploy failed · check CORS and API process",
          },
          result: {
            kind: "failed",
            title: "FAILED",
            message,
            durationLabel: "—",
            servicesLabel: "n/a",
            verificationScore: null,
            constraintsResolved: 0,
            rollbackScope: null,
          },
        });
      }
    },
    [closeStream, form, subscribe],
  );

  const startDeployment = useCallback(() => {
    if (form.mode === "real") {
      void startWithScenario(null);
      return;
    }
    void startWithScenario(form.scenario);
  }, [form.mode, form.scenario, startWithScenario]);

  const viewDemo = useCallback(() => {
    setFormState((prev) => ({ ...prev, mode: "demo", scenario: "PARTIAL_FAILURE" }));
    void startWithScenario("PARTIAL_FAILURE");
  }, [startWithScenario]);

  const openDeployment = useCallback(
    async (deploymentId: string) => {
      closeStream();
      seenEventsRef.current = new Set();
      setConnectionError(null);
      setHydrating(true);
      setSnapshot({
        ...createIdleSnapshot(),
        deploymentId,
        runStatus: "running",
        explain: {
          currentStage: null,
          round: null,
          statusLabel: "Loading",
          simpleText: `Loading run ${deploymentId} from MEDHA backend…`,
          technicalText: `source=rest+artifacts · deployment_id=${deploymentId}`,
        },
      });
      try {
        const [api, hydration] = await Promise.all([
          fetchDeployment(deploymentId),
          fetchRunHydration(deploymentId),
        ]);
        const { verification, critic } = mapVerificationArtifact(hydration.verification);
        setSnapshot(
          buildBackendSnapshot({
            api,
            logs: hydration.logs,
            constraints: hydration.constraints?.constraints ?? null,
            negotiation: hydration.constraints?.negotiation ?? null,
            verification,
            critic,
            graph: hydration.graph?.graph ?? null,
            rollback: hydration.graph?.rollback ?? null,
            changeIntel: hydration.changeImpact?.analysis ?? null,
          }),
        );
        subscribe(deploymentId);
      } catch (error) {
        const message =
          error instanceof ApiError
            ? error.message
            : `Cannot load run ${deploymentId}. Backend unreachable?`;
        setConnectionError(message);
        setSnapshot({
          ...createIdleSnapshot(),
          deploymentId,
          runStatus: "failed",
          explain: {
            currentStage: null,
            round: null,
            statusLabel: "Failed to load",
            simpleText: message,
            technicalText: `source=rest · deployment_id=${deploymentId}`,
          },
        });
      } finally {
        setHydrating(false);
      }
    },
    [closeStream, subscribe],
  );

  const value = useMemo<DeploymentContextValue>(
    () => ({
      form,
      setForm,
      viewMode,
      setViewMode,
      snapshot,
      selectNode,
      startDeployment,
      viewDemo,
      reset,
      openDeployment,
      isRunning: snapshot.runStatus === "running",
      hydrating,
      scenarios: SCENARIOS,
      connectionError,
    }),
    [
      form,
      setForm,
      viewMode,
      snapshot,
      selectNode,
      startDeployment,
      viewDemo,
      reset,
      openDeployment,
      hydrating,
      connectionError,
    ],
  );

  return (
    <DeploymentContext.Provider value={value}>{children}</DeploymentContext.Provider>
  );
}

export function useDeployment() {
  const ctx = useContext(DeploymentContext);
  if (!ctx) {
    throw new Error("useDeployment must be used within DeploymentProvider");
  }
  return ctx;
}

/**
 * Safe accessor for pages that must render shared chrome (e.g. Header) with or
 * without a DeploymentProvider in the tree. Returns null outside the provider.
 */
export function useOptionalDeployment(): DeploymentContextValue | null {
  return useContext(DeploymentContext);
}
