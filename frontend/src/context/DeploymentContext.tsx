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
  clearApiCache,
  createDeployment,
  fetchDeployment,
  fetchRunHydration,
  subscribeDeploymentEventsShared,
  type BackendSystemEvent,
  type EventSubscription,
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
  reset: () => void;
  openDeployment: (deploymentId: string) => Promise<void>;
  isRunning: boolean;
  hydrating: boolean;
  connectionError: string | null;
}

const DeploymentContext = createContext<DeploymentContextValue | null>(null);

// Product default: real repository analysis. The demo scenario engine is not
// part of the product workflow (backend demo runs are disabled by default),
// so the form never defaults to demo mode.
const DEFAULT_FORM: DeployFormState = {
  repositoryUrl: "",
  targetHost: "localhost",
  targetPort: "8080",
  intent: "",
  scenario: null,
  mode: "real",
  baseRevision: "",
  targetRevision: "",
};

export function DeploymentProvider({ children }: { children: ReactNode }) {
  const [form, setFormState] = useState<DeployFormState>(DEFAULT_FORM);
  const [viewMode, setViewMode] = useState<ViewMode>("simple");
  const [snapshot, setSnapshot] = useState<DeploymentSnapshot>(createIdleSnapshot);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [hydrating, setHydrating] = useState(false);
  const sourceRef = useRef<EventSubscription | null>(null);
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
      const subscription = subscribeDeploymentEventsShared(deploymentId, {
        onEvent: (event: BackendSystemEvent) => {
          if (seenEventsRef.current.has(event.event_id)) return;
          seenEventsRef.current.add(event.event_id);
          // Bound dedup memory for very long runs (see client MAX_SEEN).
          if (seenEventsRef.current.size > 5000) {
            const first = seenEventsRef.current.values().next().value;
            if (first) seenEventsRef.current.delete(first);
          }
          setSnapshot((prev) => applyBackendEvent(prev, event));
        },
        onTerminal: () => {
          clearApiCache(`/api/deploy/${deploymentId}`);
          closeStream();
        },
        onError: (message: string) => {
          // Surface a soft warning. If the backend actually finished the
          // deployment while the stream was down, reconcile to the terminal
          // state so the UI never stays "running".
          setConnectionError(`${message} Is the API running on :8000?`);
          fetchDeployment(deploymentId)
            .then((api) => {
              setSnapshot((prev) => reconcileTerminalState(prev, api));
              if (isTerminalDeploymentStatus(api.status)) closeStream();
            })
            .catch(() => {
              /* backend unreachable — message already shown */
            });
        },
      });
      sourceRef.current = subscription;
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
        scenario: null,
        isDemo: false,
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
          mode: "real",
          scenario: null,
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
            null,
            false,
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
          scenario: null,
          isDemo: false,
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
    // Product workflow is real-only; demo creation is not offered.
    void startWithScenario(null);
  }, [startWithScenario]);

  const openDeployment = useCallback(
    async (deploymentId: string) => {
      closeStream();
      seenEventsRef.current = new Set();
      setConnectionError(null);
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
        const [apiResult, hydrationResult] = await Promise.allSettled([
          fetchDeployment(deploymentId),
          fetchRunHydration(deploymentId),
        ]);

        const apiFetchSuccessful = apiResult.status === "fulfilled";
        const hydrationFetchSuccessful = hydrationResult.status === "fulfilled";

        if (!apiFetchSuccessful || !hydrationFetchSuccessful) {
          const apiMessage =
            !apiFetchSuccessful &&
            apiResult.reason instanceof ApiError
              ? apiResult.reason.message
              : !apiFetchSuccessful
                ? "Cannot reach MEDHA backend for run deployment data."
                : null;
          const hydMessage =
            !hydrationFetchSuccessful &&
            hydrationResult.reason
              ? hydrationResult.reason instanceof ApiError
                ? hydrationResult.reason.message
                : "Cannot fetch run hydration data."
              : null;
          const combinedMessage = [
            apiMessage,
            hydMessage,
          ]
            .filter(Boolean)
            .join(" ");
          setConnectionError(combinedMessage || "Failed to load run data.");
          setSnapshot({
            ...createIdleSnapshot(),
            deploymentId,
            runStatus: "failed",
            explain: {
              currentStage: null,
              round: null,
              statusLabel: "Failed to load",
              simpleText: combinedMessage || "Failed to load run data.",
              technicalText: `source=rest · deployment_id=${deploymentId}`,
            },
          });
          return;
        }

        const api = apiResult.value;
        const hydrate = hydrationResult.value;

        const { verification, critic } = mapVerificationArtifact(hydrate.verification);
        const constraints = hydrate.constraints?.constraints ?? null;
        const negotiation = hydrate.constraints?.negotiation ?? null;
        const graph = hydrate.graph?.graph ?? null;
        const rollback = hydrate.graph?.rollback ?? null;
        const changeIntel = hydrate.changeImpact?.analysis ?? null;

        setSnapshot(
          buildBackendSnapshot({
            api,
            logs: hydrate.logs,
            executionMode: hydrate.executionMode,
            runtimeLogs: hydrate.runtimeLogs,
            constraints,
            negotiation,
            verification,
            critic,
            graph,
            rollback,
            changeIntel,
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
      reset,
      openDeployment,
      isRunning: snapshot.runStatus === "running",
      hydrating,
      connectionError,
    }),
    [
      form,
      setForm,
      viewMode,
      snapshot,
      selectNode,
      startDeployment,
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
