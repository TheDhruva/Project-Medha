import { afterEach, describe, expect, it, vi } from "vitest";

import {
  analyzeChangeImpact,
  eventsUrl,
  fetchChangeImpact,
  fetchDemoChangeImpact,
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

  it("fetchDemoChangeImpact hits the demo fixture endpoint", async () => {
    stubFetch(
      jsonResponse({
        is_demo: true,
        label: "DEMO/MOCK",
        analysis: { risk: { level: "high" } },
      } as ChangeImpactResponse),
    );
    const r = await fetchDemoChangeImpact();
    expect(lastUrl).toMatch(/\/api\/change-impact\/demo\/fixture$/);
    expect(r.is_demo).toBe(true);
    expect(r.label).toBe("DEMO/MOCK");
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

  it("fetchRunHydration maps mode/logs and tolerates absent fields", async () => {
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
  });
});