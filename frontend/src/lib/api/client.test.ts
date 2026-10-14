import { afterEach, describe, expect, it, vi } from "vitest";

import {
  analyzeChangeImpact,
  eventsUrl,
  fetchChangeImpact,
  fetchConfigStatus,
  fetchRunHealth,
  fetchRunHydration,
  fetchRunLogs,
} from "@/lib/api/client";
import type { ChangeImpactResponse } from "@/lib/api/client";

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    statusText: ok ? "OK" : "Error",
    json: async () => body,
  } as Response;
}

let lastUrl: string | null = null;
let lastInit: RequestInit | undefined;

function stubFetch(response: Response): void {
  lastUrl = null;
  lastInit = undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      lastUrl = String(input);
      lastInit = init;
      return response;
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("change intelligence client", () => {
  it("analyzeChangeImpact POSTs the request to the analyze endpoint", async () => {
    stubFetch(jsonResponse({ analysis: { risk: { level: "low" } } }));
    const r = await analyzeChangeImpact({
      repository_url: "C:/repo",
      base_revision: "base",
      target_revision: "target",
      deployment_id: null,
    });
    expect(lastUrl).toMatch(/\/api\/change-impact\/analyze$/);
    expect(lastInit?.method).toBe("POST");
    const body = JSON.parse(String(lastInit?.body));
    expect(body).toMatchObject({
      repository_url: "C:/repo",
      base_revision: "base",
      target_revision: "target",
    });
    expect(r.analysis.risk.level).toBe("low");
  });

  it("analyzeChangeImpact surfaces backend error code", async () => {
    stubFetch(
      jsonResponse(
        { error: { code: "REPO_NOT_FOUND", message: "path missing" } },
        false,
        400,
      ),
    );
    await expect(
      analyzeChangeImpact({
        repository_url: "C:/nope",
        base_revision: "base",
        target_revision: "target",
      }),
    ).rejects.toMatchObject({ status: 400, code: "REPO_NOT_FOUND" });
  });

  it("fetchChangeImpact reads a persisted analysis by deployment id", async () => {
    stubFetch(jsonResponse({ deployment_id: "dep_1", analysis: {} } as ChangeImpactResponse));
    await fetchChangeImpact("dep_1");
    expect(lastUrl).toMatch(/\/api\/deploy\/dep_1\/change-impact$/);
  });

  it("encodes deployment ids in SSE and artifact URLs", async () => {
    expect(eventsUrl("dep_abc 123/..")).toContain(
      `/api/deploy/${encodeURIComponent("dep_abc 123/..")}/events`,
    );
    stubFetch(jsonResponse({ deployment_id: "dep_1", analysis: {} } as ChangeImpactResponse));
    await fetchChangeImpact("dep_a/b");
    expect(lastUrl).toContain(`/api/deploy/${encodeURIComponent("dep_a/b")}/change-impact`);
  });
});

describe("run health and config diagnostics", () => {
  it("fetchRunHealth hits the per-run health endpoint", async () => {
    stubFetch(
      jsonResponse({
        deployment_id: "dep_1",
        is_demo: false,
        health_status: "unknown",
        checked_at: null,
        source: "stored",
        reason: "No execution result recorded yet.",
        execution_mode: null,
      }),
    );
    const r = await fetchRunHealth("dep_1");
    expect(lastUrl).toMatch(/\/api\/deploy\/dep_1\/health$/);
    expect(r?.health_status).toBe("unknown");
  });

  it("fetchRunHealth returns null when the backend is unreachable", async () => {
    stubFetch(jsonResponse({ error: { code: "NOT_FOUND" } }, false, 404));
    await expect(fetchRunHealth("dep_missing")).resolves.toBeNull();
  });

  it("fetchConfigStatus reports presence booleans only", async () => {
    stubFetch(
      jsonResponse({
        env: "development",
        auth_mode: "off",
        executor_mode: "auto",
        docker_execute: false,
        demo_enabled: false,
        configured: { MEDHA_API_TOKEN: false, GITHUB_APP_ID: false },
        github_app_configured: false,
        docker_cli: false,
        docker_daemon: false,
        database_mode: "sqlite",
        execution: "unconfigured",
        execution_reason: "Set ...",
        production_ready: null,
      }),
    );
    const r = await fetchConfigStatus();
    expect(lastUrl).toMatch(/\/api\/config\/status$/);
    expect(r?.demo_enabled).toBe(false);
    expect(r?.configured).toMatchObject({ MEDHA_API_TOKEN: false });
  });
});

describe("run logs and hydration client", () => {
  it("fetchRunLogs passes through execution_mode and runtime_logs", async () => {
    stubFetch(
      jsonResponse({
        deployment_id: "dep_1",
        is_demo: false,
        label: null,
        execution_mode: "real",
        lines: [],
        runtime_logs: { available: true, container: "c1", stdout: "hi", stderr: "" },
      }),
    );
    const r = await fetchRunLogs("dep_1");
    expect(r.execution_mode).toBe("real");
    expect(r.runtime_logs?.stdout).toBe("hi");
  });

  it("fetchRunHydration passes through the backend agent snapshot", async () => {
    const snapshot = [
      { id: "preflight", name: "Preflight", status: "complete", activity: "Done", lastEvent: "Done", durationMs: 12.5, startedAt: "t0", finishedAt: "t1", deps: [] },
      { id: "analyzer", name: "Code Analyzer", status: "running", activity: "Analyzing", lastEvent: "Analyzing", durationMs: null, startedAt: "t1", finishedAt: null, deps: ["preflight"] },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/logs")) {
          return jsonResponse({
            deployment_id: "dep_1",
            is_demo: false,
            label: null,
            execution_mode: "controlled_test",
            lines: [],
            agents: snapshot,
            runtime_logs: null,
          });
        }
        return jsonResponse({});
      }),
    );
    const h = await fetchRunHydration("dep_1");
    expect(h.agents).toEqual(snapshot);
  });

  it("fetchRunHydration maps absent agents to null (honest unknown)", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        calls.push(url);
        if (url.endsWith("/logs")) {
          return jsonResponse({
            deployment_id: "dep_1",
            is_demo: false,
            label: null,
            execution_mode: "controlled_test",
            lines: [],
            runtime_logs: { available: false, container: "c1", code: "LOGS_UNAVAILABLE" },
          });
        }
        if (url.endsWith("/change-impact")) {
          return jsonResponse({ error: { code: "NOT_FOUND" } }, false, 404);
        }
        return jsonResponse({});
      }),
    );
    const h = await fetchRunHydration("dep_1");
    expect(h.executionMode).toBe("controlled_test");
    expect(h.runtimeLogs?.code).toBe("LOGS_UNAVAILABLE");
    expect(h.logs).toEqual([]);
    expect(h.agents).toBeNull();
  });
});